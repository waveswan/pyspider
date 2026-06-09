# Server Parser Prompt

Используй этот промпт, когда нужно создать или доработать pyspider-парсер прямо на сервере, без локального запуска на машине пользователя.

```text
Нужно создать или доработать pyspider-парсер для сайта: <SITE_URL>.

Работай напрямую с сервером pyspider.

Доступ:
- SSH host: <SSH_HOST>
- SSH user: <SSH_USER>
- SSH auth: <SSH_PASSWORD_OR_KEY_PROVIDED_IN_CHAT>

Важно:
- не записывай пароль, прокси, cookies, токены и другие секреты в файлы проекта;
- не трогай существующий серверный parser/component-parser;
- все команды Docker выполняй только для проекта pyspider-modernized;
- рабочая папка pyspider на сервере: /home/deploy/pyspider-modernized;
- веб-интерфейс pyspider на сервере: http://127.0.0.1:5050 внутри сервера и http://<SSH_HOST>:5050 снаружи;
- pyspider запущен через Docker Compose: docker compose -p pyspider-modernized -f docker-compose.server.yml ...

Стандарт результата:
- изучи /home/deploy/pyspider-modernized/parser_workspace/docs/parser-standard.md;
- используй /home/deploy/pyspider-modernized/parser_workspace/templates/pyspider_product_parser.py как основу;
- итоговый результат detail_page должен соответствовать parser-standard.md;
- поле `group` в результате товара означает Marketlab database group; если пользователь не указал иначе, используй `electronik`;
- не путай товарный `result["group"]` с pyspider project group в Web UI;
- картинки, файлы, документация и 3D-модели должны скачиваться на сервер и сохраняться в результате локальными публичными путями;
- документация хранится как [{"name": "...", "url": "..."}];
- 3D-модели хранятся в models_3d как список локальных публичных путей.

Порядок работы:
1. Подключись по SSH.
2. Проверь, что нужный стек работает:
   cd /home/deploy/pyspider-modernized
   docker compose -p pyspider-modernized -f docker-compose.server.yml ps
   docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}'
3. Убедись, что старый parser/component-parser не трогаешь. Он может работать параллельно на другом порту.
4. Проверь pyspider:
   curl -I http://127.0.0.1:5050/
   curl -s http://127.0.0.1:5050/proxy-config
5. Создай тестовый проект <donor>_test, а не боевой <donor>.
6. Файл парсера сохраняй на сервере:
   /home/deploy/pyspider-modernized/parser_workspace/projects/<donor>_test.py
7. Не делай полный обход каталога сразу. Первый прогон: 3-5 карточек товара.
8. Загрузи код в pyspider через серверный web endpoint:
   curl -sS -X POST \
     http://127.0.0.1:5050/debug/<donor>_test/save \
     --data-urlencode script@/home/deploy/pyspider-modernized/parser_workspace/projects/<donor>_test.py
9. Поставь безопасную скорость и статус DEBUG:
   curl -sS -X POST http://127.0.0.1:5050/update \
     -d pk=<donor>_test \
     -d name=rate \
     -d value='0.2/1'
   curl -sS -X POST http://127.0.0.1:5050/update \
     -d pk=<donor>_test \
     -d name=status \
     -d value=DEBUG
10. Запусти тест:
   curl -sS -X POST http://127.0.0.1:5050/run -d project=<donor>_test
11. Смотри логи:
   docker compose -p pyspider-modernized -f docker-compose.server.yml logs -f pyspider
12. Проверяй задачи и результаты в MongoDB контейнере:
   docker compose -p pyspider-modernized -f docker-compose.server.yml exec -T mongo \
     mongosh taskdb --quiet --eval 'db.getCollection("<donor>_test").aggregate([{$group:{_id:"$status", count:{$sum:1}}}]).toArray()'
   docker compose -p pyspider-modernized -f docker-compose.server.yml exec -T mongo \
     mongosh resultdb --quiet --eval 'db.getCollection("<donor>_test").countDocuments()'
   docker compose -p pyspider-modernized -f docker-compose.server.yml exec -T mongo \
     mongosh resultdb --quiet --eval 'db.getCollection("<donor>_test").find({}, {_id:0}).limit(3).toArray()'
13. Если есть ошибки, исправь файл парсера на сервере, снова загрузи через /debug/<project>/save и повтори тест.
14. После успешного теста останови проект:
   curl -sS -X POST http://127.0.0.1:5050/update \
     -d pk=<donor>_test \
     -d name=status \
     -d value=STOP
15. В финале покажи:
   - путь к файлу парсера на сервере;
   - статус контейнеров;
   - task_status_count;
   - result_count;
   - 3 кратких примера результата;
   - список скачанных ассетов: картинки, files/documents/models_3d;
   - что готово для переноса в боевой проект <donor>.

Правила безопасности:
- не запускай docker compose down для чужих проектов;
- не используй docker stop/rm без точного имени контейнера pyspider-modernized;
- не чисти MongoDB и volumes;
- не делай полный RUNNING-обход без отдельного подтверждения пользователя;
- перед любыми командами, которые могут удалить данные, остановить контейнеры или затронуть другой проект, остановись и спроси разрешение;
- если нужно использовать прокси, добавляй их через web UI или /proxy-config, но не коммить прокси в Git.
```

## Короткая версия для нового чата

```text
Работай напрямую с сервером pyspider по инструкции из:
/home/deploy/pyspider-modernized/parser_workspace/prompts/server-parser.md

Создай тестовый парсер <donor>_test для <SITE_URL>.
Не работай локально. Не трогай component-parser.
Сначала 3-5 товаров, потом останови проект и покажи task_status_count, result_count и 3 примера результата.
```
