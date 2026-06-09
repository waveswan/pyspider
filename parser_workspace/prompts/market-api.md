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
- `group` в legacy Marketlab исторически означает группу/коллекцию товаров внутри `resultdb`. Теперь `group` нужно поддержать как безопасный выбор коллекции, например `group=electronik` -> Mongo namespace `resultdb.electronik`.

Текущая MongoDB-реальность pyspider:
- pyspider использует MongoDB сервис `mongo`.
- config_server.json:
  - taskdb: mongodb+taskdb://mongo:27017/taskdb
  - projectdb: mongodb+projectdb://mongo:27017/projectdb
  - resultdb: mongodb+resultdb://mongo:27017/resultdb
- Для Marketlab API товары должны лежать в коллекциях по `group` внутри базы `resultdb`.
- На текущем этапе у нас один реально рабочий парсер: `cnlinko`.
- Его товары должны попадать в одну целевую коллекцию:
  - `resultdb.electronik`, если `group=electronik`;
  - в общем виде `resultdb.<group>`.
- Не строить логику вокруг множества pyspider-проектов и `resultdb.<project>`.
- Если старые тестовые коллекции вроде `resultdb.cnlinko_test` существуют, считать их временным наследием разработки, а не источником для legacy API.
- В документах `resultdb.<group>` товар должен быть сохранен как обычный MongoDB-документ с полями из parser_workspace/docs/parser-standard.md. API не должен требовать обертку pyspider вида `{taskid, url, result}` для основной выдачи.

Главная архитектурная задача:
Сделай API, который читает товары из одной коллекции `resultdb.<group>`.

Рекомендуемая целевая модель:
- `group` выбирает MongoDB collection внутри базы `resultdb`;
- товары хранятся в одной коллекции на группу;
- для текущей задачи основной group: `electronik`;
- пример:
  - request: `/market/parsing/catalog?api_key=...&group=electronik&donor=cnlinko&page=1`
  - Mongo source для API: database `resultdb`, collection `electronik`.

Важно по безопасности:
- не использовать `group` как произвольное имя коллекции без проверки;
- разрешенные group/collections задать whitelist-настройкой, например:
  - `MARKET_API_ALLOWED_GROUPS=electronik`
  - или `MARKET_API_GROUP_COLLECTION_MAP=electronik:electronik`
- если `group` не передан, использовать `MARKET_API_DEFAULT_GROUP=electronik`;
- если `group` неизвестный, вернуть HTTP 400:
  `{"detail": "Unknown group"}`.

Почему:
- legacy API должно быстро искать и фильтровать;
- нужны индексы по donor/vendor/categories/name;
- Marketlab уже умеет передавать `group`, и это нужно использовать для выбора коллекции товаров;
- сейчас нужно поддержать прежде всего один донорский поток: `cnlinko` -> `resultdb.electronik`.

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
- API читает из MongoDB `resultdb.<group>`.
- Не создавать отдельную товарную базу/коллекцию для API как основной источник.
- Для `group=electronik` source of truth:
  mongodb://mongo:27017/resultdb, collection electronik
- Настроить через env:
  - MARKET_API_MONGO_URL=mongodb://mongo:27017
  - MARKET_API_RESULT_DB=resultdb
  - MARKET_API_DEFAULT_GROUP=electronik
  - MARKET_API_ALLOWED_GROUPS=electronik
  - MARKET_API_GROUP_COLLECTION_MAP=electronik:electronik
  - MARKET_API_SOURCE_PROJECT=cnlinko
  - PARSER_API_KEY=<secret>
  - PAGE_SIZE=100

Запись товаров из парсера:
- Переписать/довести один рабочий парсер `cnlinko`, чтобы итоговые товары попадали в `resultdb.<group>`, где group по умолчанию `electronik`.
- Не плодить отдельные API-source коллекции по имени проекта.
- Если используется pyspider `on_result`, он должен upsert-ить товар в `resultdb.electronik`.
- Upsert делать по стабильному ключу:
  - external_id, если есть;
  - иначе id, если есть;
  - иначе donor_url;
  - иначе source_taskid/taskid.
- Вместе с товаром сохранить технические поля:
  - source_project: "cnlinko";
  - source_taskid;
  - source_url;
  - source_updatetime;
  - updated_at.

Опциональный CLI repair/sync:
- Можно добавить команду для переноса старых тестовых данных из `resultdb.cnlinko` или `resultdb.cnlinko_test` в `resultdb.electronik`, но это вспомогательная миграция, а не основная архитектура.
- Пример:
  python -m market_api.sync --group electronik --source-project cnlinko

Нормализация товара:
- Pyspider parser-standard использует часть camelCase и часть snake_case.
- API должно отдавать camelCase, как ждёт legacy Meteor.
- Поддержать оба входных варианта:
  - typePrefix и type_prefix;
  - external_id и id;
  - old_price и oldPrice, если пригодится;
  - main_image и mainImage.
- Поля документа в `resultdb.<group>`:
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
- Игнорировать неизвестные query params, но `group` не игнорировать: использовать его как безопасный выбор коллекции внутри `resultdb` через whitelist/map.
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
    - MARKET_API_RESULT_DB=resultdb
    - MARKET_API_DEFAULT_GROUP=electronik
    - MARKET_API_ALLOWED_GROUPS=electronik
    - MARKET_API_GROUP_COLLECTION_MAP=electronik:electronik
    - MARKET_API_SOURCE_PROJECT=cnlinko
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
     python -m market_api.sync --group electronik --source-project cnlinko
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
- товары для legacy API должны лежать в Mongo resultdb.<group>, например resultdb.electronik;
- у нас один рабочий парсер: cnlinko; его товары нужно писать/мигрировать в resultdb.electronik;
- API endpoints: /health, /market/parsing/search, /market/parsing/catalog;
- api_key брать из env PARSER_API_KEY;
- Docker service market-api, внешний порт 8081, не использовать 8000;
- не трогать существующий component-parser на сервере;
- ответы должны быть JSON и совместимы с legacy Meteor response.data.items / response.data.finish.
```
