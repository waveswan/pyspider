# Market API Prompt

Используй этот промпт в новом чате, когда нужно реализовать backend API для legacy Meteor Marketlab 2.5 на базе текущего pyspider-проекта.

```text
Нужно разработать backend API для восстановления импорта товаров из донорских pyspider-парсеров в legacy Meteor-приложение Marketlab 2.5.

Работай в репозитории pyspider:
- локально: /Users/dimitrii/Projects/Other/pyspider
- на сервере: /home/deploy/pyspider-modernized

Контекст проекта:
- Это модернизированный pyspider на Python 3.11.
- Pyspider уже работает в Docker Compose.
- Web UI pyspider:
  - локально: http://127.0.0.1:5050/
  - сервер: http://94.241.173.2:5050/
- На сервере есть другой парсер component-parser. Его не трогать.
- Не использовать порт 8000 на сервере, он занят существующим component-parser.
- Для нового API использовать отдельный FastAPI-сервис, например внешний порт 8081 и внутренний порт 8080.
- На этом этапе не нужно строить универсальную платформу для всех доноров. Реально рабочий парсер, который нужно переписать/довести до API, это `cnlinko`.
- `group` в legacy Marketlab исторически означал базу данных, из которой нужно читать товары. Теперь `group` нужно поддержать как безопасный выбор целевой MongoDB-базы, например `group=electronik` -> база `electronik`.

Текущая MongoDB-реальность pyspider:
- pyspider использует MongoDB сервис `mongo`.
- config_server.json:
  - taskdb: mongodb+taskdb://mongo:27017/taskdb
  - projectdb: mongodb+projectdb://mongo:27017/projectdb
  - resultdb: mongodb+resultdb://mongo:27017/resultdb
- В resultdb нет единой products-коллекции.
- Результаты лежат в отдельных коллекциях по имени pyspider-проекта:
  - resultdb.entero_test
  - resultdb.cnlinko_test
  - и будущие resultdb.<project>
- В каждом документе resultdb поле `result` хранит JSON-строку или JSON-объект с товаром, который соответствует parser_workspace/docs/parser-standard.md.

Главная архитектурная задача:
Сделай API не напрямую по всем resultdb-коллекциям, а через нормализованную товарную коллекцию в целевой базе Marketlab.

Рекомендуемая целевая модель:
- `group` выбирает MongoDB database;
- товары хранятся в одной коллекции внутри этой базы;
- имя коллекции вынести в env, default `parsed_products`;
- пример:
  - request: `/market/parsing/catalog?api_key=...&group=electronik&donor=cnlinko&page=1`
  - Mongo source для API: database `electronik`, collection `parsed_products`.

Важно по безопасности:
- не использовать `group` как произвольное имя базы без проверки;
- разрешенные базы задать whitelist-настройкой, например:
  - `MARKET_API_ALLOWED_GROUPS=electronik`
  - или `MARKET_API_GROUP_DB_MAP=electronik:electronik`
- если `group` не передан, использовать `MARKET_API_DEFAULT_GROUP=electronik`;
- если `group` неизвестный, вернуть HTTP 400:
  `{"detail": "Unknown group"}`.

Почему:
- legacy API должно быстро искать и фильтровать;
- нужны индексы по donor/vendor/categories/name;
- pyspider resultdb хранит данные по коллекциям проектов, что неудобно для API;
- Marketlab уже умеет передавать `group`, и это можно использовать для выбора бизнес-базы;
- сейчас нужно поддержать прежде всего один донорский поток: `cnlinko` -> `electronik.parsed_products`.

Рекомендуемая структура:
- новый пакет/папка: market_api/
- FastAPI приложение: market_api/main.py
- настройки: market_api/settings.py
- Mongo client/repository: market_api/db.py
- схемы Pydantic: market_api/schemas.py
- нормализация товара: market_api/normalizer.py
- CLI/скрипт синхронизации: market_api/sync.py
- Dockerfile для API: Dockerfile.api
- обновить docker-compose.server.yml, добавив сервис `market-api`
- обновить docker-compose.local.yml, добавив сервис `market-api`
- добавить `.env.example` без секретов

API source of truth:
- API читает из MongoDB коллекции `parsed_products` в базе, выбранной через `group`.
- Не использовать отдельную общую базу `market_api` как основной источник товаров, если legacy ожидает `group` как ссылку на бизнес-базу.
- Для `group=electronik` source of truth:
  mongodb://mongo:27017/electronik, collection parsed_products
- Настроить через env:
  - MARKET_API_MONGO_URL=mongodb://mongo:27017
  - MARKET_API_DEFAULT_GROUP=electronik
  - MARKET_API_ALLOWED_GROUPS=electronik
  - MARKET_API_GROUP_DB_MAP=electronik:electronik
  - MARKET_API_COLLECTION=parsed_products
  - MARKET_API_SOURCE_PROJECTS=cnlinko
  - PARSER_API_KEY=<secret>
  - PAGE_SIZE=100

Синхронизация из pyspider resultdb:
- Реализуй команду, которую можно запускать внутри API-контейнера:
  python -m market_api.sync
- Команда должна:
  1. подключиться к MongoDB;
  2. читать только разрешенные source-проекты из `MARKET_API_SOURCE_PROJECTS`, на первом этапе это `cnlinko`;
  3. прочитать документы с полями taskid, url, result, updatetime;
  4. распарсить result, если это JSON-строка;
  5. пропустить пустые/не товарные результаты;
  6. нормализовать поля в `<target_db>.parsed_products`, где target_db выбран из `MARKET_API_DEFAULT_GROUP` или явного аргумента sync-команды;
  7. сделать upsert по стабильному ключу:
     - external_id, если есть;
     - иначе id, если есть;
     - иначе taskid;
     - вместе с donor/project, чтобы не было конфликтов;
  8. сохранить source_project, source_taskid, source_url, source_updatetime.

CLI sync должен поддержать явный group:
  python -m market_api.sync --group electronik --project cnlinko

Если `--project` не передан, использовать `MARKET_API_SOURCE_PROJECTS`.
Если `--group` не передан, использовать `MARKET_API_DEFAULT_GROUP`.

Нормализация товара:
- Pyspider parser-standard использует часть camelCase и часть snake_case.
- API должно отдавать camelCase, как ждёт legacy Meteor.
- Поддержать оба входных варианта:
  - typePrefix и type_prefix;
  - external_id и id;
  - old_price и oldPrice, если пригодится;
  - main_image и mainImage.
- Поля документа parsed_products:
  {
    "_id": ObjectId,
    "external_id": "stable-id",
    "donor": "cnlinko",
    "name": "CNLinko connector example",
    "vendor": "CNLinko",
    "model": "LP-16",
    "artnumber": "LP-16",
    "type_prefix": "Разъем",
    "categories": ["Connectors", "Circular connectors", "SA series"],
    "currency": "RUB",
    "price": 123.45,
    "prices": [],
    "images": ["https://..."],
    "icon": "https://...",
    "main_image": "https://...",
    "characteristics": [{"name": "Количество контактов", "value": "10"}],
    "description": "Описание товара",
    "files": [],
    "documents": [{"name": "Инструкция", "url": "/upload/..."}],
    "models_3d": [],
    "source_project": "cnlinko",
    "source_taskid": "...",
    "source_url": "...",
    "created_at": datetime,
    "updated_at": datetime
  }

Индексы MongoDB:
- donor
- vendor
- categories
- name
- donor + categories
- donor + vendor
- source_project + source_taskid unique
- text index по name, vendor, model, artnumber, description для /search

Авторизация:
- Проверять query param `api_key`.
- Значение брать только из env `PARSER_API_KEY`.
- Не коммитить реальный ключ.
- Если ключ отсутствует в env, API может стартовать, но защищенные endpoints должны возвращать 403 или явную ошибку конфигурации. Лучше валидировать на старте и логировать warning.
- Если ключ неверный, вернуть HTTP 403:
  {"detail": "Invalid api_key"}

Общие требования:
- API возвращает только JSON.
- Не возвращать HTML.
- Добавить OpenAPI-документацию FastAPI.
- Добавить Pydantic response models.
- Игнорировать неизвестные query params, но `group` не игнорировать: использовать его как безопасный выбор MongoDB-базы через whitelist/map.
- Не падать, если у товара нет необязательных полей.
- Добавить обработку ошибок MongoDB:
  - при ошибке подключения вернуть 503;
  - тело: {"detail": "MongoDB unavailable"}.
- API должно быть совместимо со старым Meteor HTTP.call:
  - Meteor должен читать response.data.items;
  - для catalog должен читать response.data.finish.

Endpoint 1:
GET /health

Ответ:
{"status": "ok"}

Endpoint 2:
GET /market/parsing/search

Назначение:
Поиск товаров по строке. Используется для поиска похожих товаров/синонимов у доноров.

Query params:
- api_key: string, обязательный
- q: string, обязательный поисковый запрос

Необязательные параметры, которые можно игнорировать:
- page
- donor
- vendor
- catalog

Дополнительный параметр:
- group: optional, default `MARKET_API_DEFAULT_GROUP`; выбирает MongoDB-базу через whitelist/map.

Поведение:
- Если q пустой, вернуть {"items": []}.
- Использовать Mongo text search, если text index есть.
- Если text search недоступен, fallback на case-insensitive regex по:
  - name
  - vendor
  - model
  - artnumber
- Ограничить выдачу настройкой SEARCH_LIMIT, например 50.

Ответ:
{
  "items": [
    {
      "name": "Название товара",
      "donor": "cnlinko",
      "price": 123.45,
      "typePrefix": "Разъем",
      "vendor": "CNLinko",
      "model": "LP-16",
      "artnumber": "LP-16",
      "images": ["https://..."],
      "characteristics": [
        {"name": "Количество контактов", "value": "10"}
      ],
      "description": "Описание товара"
    }
  ]
}

Минимально обязательные поля в каждом item:
- name
- donor

Остальные поля возвращать, если они есть в базе.

Endpoint 3:
GET /market/parsing/catalog

Назначение:
Постраничная выдача товаров конкретного донора/каталога. Этот endpoint используется для наполнения Checkmodels и последующего построения каталога в Marketlab.

Query params:
- api_key: string, обязательный
- donor: string, обязательный, например "cnlinko"
- page: integer, optional, default 1
- catalog: string, optional, default ""
- vendor: string, optional, default ""
- group: optional, default `MARKET_API_DEFAULT_GROUP`; выбирает MongoDB-базу через whitelist/map, например `electronik`.

Фильтрация:
- donor фильтрует по donor;
- vendor фильтрует по vendor, если передан;
- catalog фильтрует товары, у которых categories содержит указанную категорию;
- если catalog пустой, вернуть все товары донора.

Pagination:
- page начинается с 1;
- PAGE_SIZE брать из env, default 100;
- запросить PAGE_SIZE + 1 документов;
- finish=false, если есть следующая страница;
- finish=true, если это последняя страница;
- если товаров нет:
  {"finish": true, "items": []}

Ответ:
{
  "finish": false,
  "items": [
    {
      "id": "external-product-id",
      "name": "CNLinko connector example",
      "donor": "cnlinko",
      "vendor": "CNLinko",
      "model": "LP-16",
      "artnumber": "LP-16",
      "typePrefix": "Разъем",
      "categories": ["Connectors", "Circular connectors", "SA series"],
      "currency": "RUB",
      "price": 123.45,
      "prices": [],
      "images": ["https://..."],
      "icon": "https://...",
      "characteristics": [
        {"name": "Количество контактов", "value": "10"}
      ],
      "description": "Описание товара"
    }
  ]
}

Критически важные поля:
- name
- categories
- donor

Желательные поля:
- vendor
- model
- artnumber
- typePrefix
- price
- currency
- images
- icon
- characteristics
- description

Совместимость имен:
- В Mongo можно хранить snake_case.
- В API ответе строго camelCase:
  - type_prefix -> typePrefix
  - external_id -> id
  - main_image -> mainImage, если поле понадобится
  - models_3d можно вернуть как models3d или models_3d только если legacy это ожидает; для текущих endpoints это поле не обязательно.

Docker:
- Добавить Dockerfile.api.
- Добавить сервис в docker-compose.server.yml:
  - name: market-api
  - build: Dockerfile.api
  - depends_on: mongo healthy
  - network: pyspider
  - ports: "8081:8080"
  - env:
    - MARKET_API_MONGO_URL=mongodb://mongo:27017
    - MARKET_API_DEFAULT_GROUP=electronik
    - MARKET_API_ALLOWED_GROUPS=electronik
    - MARKET_API_GROUP_DB_MAP=electronik:electronik
    - MARKET_API_COLLECTION=parsed_products
    - MARKET_API_SOURCE_PROJECTS=cnlinko
    - PARSER_API_KEY=${PARSER_API_KEY}
    - PAGE_SIZE=100
- Добавить такой же сервис в docker-compose.local.yml.
- Не ломать текущие pyspider и mongo services.

Тесты:
- Добавить unit-тесты для normalizer.
- Добавить API-тесты через pytest + TestClient.
- Проверить:
  1. GET /health возвращает {"status": "ok"}.
  2. Неверный api_key возвращает 403 {"detail": "Invalid api_key"}.
  3. Query param group выбирает разрешенную базу, например electronik, и не ломает /search и /catalog.
  4. /market/parsing/search?api_key=...&q=<known_cnlinko_query>&group=electronik возвращает {"items": [...]}.
  5. /market/parsing/catalog?api_key=...&donor=cnlinko&page=1&group=electronik возвращает {"finish": bool, "items": [...]}.
  6. /catalog возвращает categories как массив строк.
  7. Товар без необязательных полей не ломает response serialization.
  8. Pagination finish работает при 0, 1, PAGE_SIZE и PAGE_SIZE+1 товарах.

Проверка на сервере:
1. Не трогай component-parser.
2. Зайди в /home/deploy/pyspider-modernized.
3. Подтяни/загрузи изменения.
4. Собери только нужный стек:
   docker compose -p pyspider-modernized -f docker-compose.server.yml up -d --build market-api
5. Выполни синхронизацию:
   docker compose -p pyspider-modernized -f docker-compose.server.yml exec -T market-api \
     python -m market_api.sync --group electronik --project cnlinko
6. Проверь:
   curl -s http://127.0.0.1:8081/health
   curl -s 'http://127.0.0.1:8081/market/parsing/search?api_key=<key>&q=<known_cnlinko_query>&group=electronik'
   curl -s 'http://127.0.0.1:8081/market/parsing/catalog?api_key=<key>&donor=cnlinko&page=1&group=electronik'

Acceptance criteria:
1. GET /health возвращает JSON status ok.
2. GET /market/parsing/search?api_key=...&q=<known_cnlinko_query>&group=electronik возвращает {items: [...]}.
3. GET /market/parsing/catalog?api_key=...&donor=cnlinko&page=1&group=electronik возвращает {finish, items}.
4. Ответ /catalog содержит categories как массив строк.
5. Query param group выбирает разрешенную базу, а неизвестный group возвращает 400.
6. Старый Meteor-код может читать response.data.items и response.data.finish без изменений.
7. API работает в Docker рядом с pyspider.
8. Существующий component-parser на сервере не остановлен и не изменен.
9. Реальный PARSER_API_KEY не попал в Git.
```

## Короткая версия для нового чата

```text
Разработай FastAPI backend API для legacy Meteor Marketlab 2.5 на базе текущего pyspider-проекта.

Используй полный промпт из:
parser_workspace/prompts/market-api.md

Ключевые реалии проекта:
- pyspider results лежат в Mongo resultdb, по коллекциям resultdb.<project>, внутри поля result;
- сделай нормализованную коллекцию electronik.parsed_products, где group=electronik выбирает базу electronik;
- API endpoints: /health, /market/parsing/search, /market/parsing/catalog;
- api_key брать из env PARSER_API_KEY;
- Docker service market-api, внешний порт 8081, не использовать 8000;
- не трогать существующий component-parser на сервере;
- ответы должны быть JSON и совместимы с legacy Meteor response.data.items / response.data.finish.
```
