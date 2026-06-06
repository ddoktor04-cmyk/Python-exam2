# NetDevOps Toolkit — Star Wars API → MSSQL ETL

> Python-проєкт для імпорту даних із [Star Wars API](https://swapi.info) до Microsoft
> SQL Server, побудований на архітектурі [Agent Skills](https://agentskills.io/specification).

## Що це

Ідемпотентний ETL-процес: дані з публічного Star Wars API завантажуються в локальну
базу Microsoft SQL Server, нормалізуються у 6 головних + 10 зв'язуючих таблиць і
залишаються доступними для аналітики через CLI чи інтерактивне меню.

Окрім ETL, проєкт містить набір допоміжних інструментів для інспекції MSSQL,
bulk-seed тестових даних, а також базові NetDevOps-утиліти (підключення до
пристроїв, рендеринг конфігів, бекап у Git).

## Демо за 30 секунд

```powershell
# 1. Активувати venv
.\.venv\Scripts\Activate.ps1

# 2. Імпортувати всі дані з SWAPI в MSSQL
python .agents/skills/swapi-etl/scripts/swapi_etl.py import all

# 3. Подивитись результат
python .agents/skills/swapi-etl/scripts/swapi_etl.py show stats
```

Очікуваний результат: 60 планет, 6 фільмів, 37 видів, 82 персонажі, 39 транспортних
засобів, 36 зорельотів — без дублікатів, навіть якщо команду запустити двічі.

## Швидкий старт з іншої машини

### Вимоги

- **Python 3.8+** (тестовано на 3.14)
- **Microsoft SQL Server 2017+** (або Azure SQL, AWS RDS, ...)
- Мережевий доступ до SQL Server (за замовчуванням порт 1433)
- Інтернет-доступ до `https://swapi.info`
- ~50 МБ вільного диска

### 1. Клонувати

```bash
git clone https://github.com/ddoktor04-cmyk/Python-exam2.git
cd Python-exam2
```

### 2. Віртуальне середовище

**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**Linux / macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Залежності

```bash
pip install -r requirements.txt
```

`requirements.txt` містить: `pymssql`, `httpx`, `jinja2`, `pyyaml`, `pydantic`,
`requests`, `faker`, `netmiko`, `scrapli`, `ncclient`, `textfsm`, `ntc-templates`.

### 4. Конфігурація підключення до БД

```bash
# Windows
copy .env.example .env

# Linux / macOS
cp .env.example .env
```

Файл `.env.example` містить шаблон для NetDevOps-змінних. Додайте у ваш `.env`
(або розширте `.env.example` локально) три обов'язкові змінні для підключення
до MSSQL:

```dotenv
DB_IP=your-mssql-host       # IP або hostname SQL Server
DB_USER=sa                  # користувач БД
DB_PASSWORD=YourStrong!Pass # пароль (НІКОЛИ не комітити .env)
DB_NAME=master              # default БД для утиліт (mssql-query, тощо)
```

> Усі скіли автоматично знаходять `.env`, піднімаючись від поточного каталогу
> та від location скрипта. Тому скрипт працює однаково з будь-якої директорії
> всередині проєкту.

### 5. Перевірити з'єднання

```powershell
python .agents/skills/mssql-query/scripts/run_query.py `
    --query "SELECT @@VERSION AS version" --format text
```

Якщо повертається версія SQL Server — все готово. Якщо `pymssql.OperationalError`,
див. розділ [Troubleshooting](#troubleshooting) унизу.

### 6. Запустити ETL

```powershell
# Інтерактивне меню
python .agents/skills/swapi-etl/scripts/swapi_etl.py

# Або одразу імпортувати все
python .agents/skills/swapi-etl/scripts/swapi_etl.py import all
```

При першому запуску скрипт:
1. Створить базу `Starwars`, якщо її немає (`CREATE DATABASE [Starwars]`).
2. Створить 16 таблиць (`IF OBJECT_ID(...) IS NULL ...`).
3. Завантажить дані з 6 ресурсів SWAPI.
4. Заповнить 10 junction-таблиць зв'язками.

## Інтерактивне меню

```powershell
python .agents/skills/swapi-etl/scripts/swapi_etl.py
```

```
=== ГОЛОВНЕ МЕНЮ ===
1. Імпорт даних
2. Показати дані
3. Видалити таблиці
0. Вихід
Ваш вибір:
```

### 1. Імпорт даних

```
--- Імпорт ---
1. Films              4. Starships
2. People             5. Species
3. Planets            6. Vehicles
                      7. Все
                      0. Назад
```

- `1`–`6` — імпортувати один ресурс (`MERGE` upsert за `swapi_url`).
- `7` — послідовно імпортувати всі 6.
- `0` — назад у головне меню.

### 2. Показати дані

```
--- Показати ---
1. Films              4. Starships
2. People             5. Species
3. Planets            6. Vehicles
                      7. Статистика
                      0. Назад
```

- `1`–`6` — перші 5 рядків у табличному форматі (URL скорочуються до `/resource/id`).
- `7` — лічильники записів у кожній таблиці + перевірка junction на ізольовані рядки.

### 3. Видалити таблиці

- Потребує підтвердження `yes/no`.
- Видаляє всі 16 таблиць у `Starwars` (але не саму базу).

### 0. Вихід

- `0` у головному меню — завершити роботу.
- `0` у підменю — повернутися на рівень вище.

## CLI-режим (для скриптів / cron)

```powershell
# Імпорт
python .agents/skills/swapi-etl/scripts/swapi_etl.py init                   # CREATE DATABASE + CREATE TABLE
python .agents/skills/swapi-etl/scripts/swapi_etl.py import films            # лише фільми
python .agents/skills/swapi-etl/scripts/swapi_etl.py import all              # все (topological order)

# Перегляд
python .agents/skills/swapi-etl/scripts/swapi_etl.py show people            # 5 рядків
python .agents/skills/swapi-etl/scripts/swapi_etl.py show people --limit 20
python .agents/skills/swapi-etl/scripts/swapi_etl.py show people --format csv
python .agents/skills/swapi-etl/scripts/swapi_etl.py show people --format json
python .agents/skills/swapi-etl/scripts/swapi_etl.py show people --select name,birth_year,gender
python .agents/skills/swapi-etl/scripts/swapi_etl.py show stats

# Обслуговування
python .agents/skills/swapi-etl/scripts/swapi_etl.py drop --yes              # видалити всі таблиці
```

Доступні формати виводу: `text` (default, вирівняна таблиця), `md` (Markdown),
`csv` (експорт), `json` (масив об'єктів).

## Структура бази даних

Після першого запуску `init` (або `import all`) у SQL Server створюється база
`Starwars` із 16 таблиць.

### Головні таблиці (6)

| Таблиця | Опис | Джерело |
| --- | --- | --- |
| `sw_films` | Фільми саги | `https://swapi.info/api/films/` |
| `sw_people` | Персонажі | `https://swapi.info/api/people/` |
| `sw_planets` | Планети | `https://swapi.info/api/planets/` |
| `sw_starships` | Зорельоти | `https://swapi.info/api/starships/` |
| `sw_vehicles` | Транспорт | `https://swapi.info/api/vehicles/` |
| `sw_species` | Види (раси) | `https://swapi.info/api/species/` |

Кожна головна таблиця має:
- `id INT` — первинний ключ із SWAPI;
- `swapi_url NVARCHAR(500)` — natural key для дедуплікації;
- `name` (або `title` для фільмів);
- інші поля за схемою SWAPI;
- `UNIQUE` constraint на `id` + `swapi_url` для захисту від дублів.

### Зв'язуючі (junction) таблиці (10)

Відносини "багато-до-багатьох" між ресурсами:

| Junction | Ліва сторона | Права сторона |
| --- | --- | --- |
| `sw_junction_film_characters` | films | people |
| `sw_junction_film_planets` | films | planets |
| `sw_junction_film_starships` | films | starships |
| `sw_junction_film_vehicles` | films | vehicles |
| `sw_junction_film_species` | films | species |
| `sw_junction_people_species` | people | species |
| `sw_junction_people_starships` | people | starships |
| `sw_junction_people_vehicles` | people | vehicles |
| `sw_junction_vehicle_pilots` | vehicles | people |
| `sw_junction_starship_pilots` | starships | people |

Кожна junction-таблиця має складений PK `(left_id, right_id)` і перезаписується
при кожному імпорті головної таблиці — це гарантує консистентність зв'язків.

### Ідемпотентність

- Усі `import_*` використовують `MERGE ... WHEN NOT MATCHED THEN INSERT ...
  WHEN MATCHED THEN UPDATE` з natural key `swapi_url`.
- Повторний запуск показує `inserted=0, updated=N` для всіх таблиць.
- Junction-таблиці очищаються й перезаповнюються при кожному імпорті головної
  таблиці — це передбачувано й усуває "висячі" зв'язки.

## Інші скіли

| Скіл | Призначення | Запуск |
| --- | --- | --- |
| `mssql-schema-inspect` | Перегляд databases/tables/columns/keys/indexes | `inspect_schema.py databases` |
| `mssql-query` | SELECT із виводом text/json/csv/md (read-only guard) | `run_query.py --query "..."` |
| `mssql-bulk-seed` | Генерація N синтетичних рядків через faker | `bulk_seed.py --table Users --rows 1000` |
| `swapi-fetch` | Сирий запит до SWAPI (URL resolution, дисковий кеш) | `swapi_fetch.py people --limit 5` |
| `netdevops-connect` | SSH / NETCONF / RESTCONF до пристрою | `connect_device.py --device r1` |
| `netdevops-config-render` | Jinja2 → конфіг + pydantic валідація | `render_config.py --template bgp.j2` |
| `netdevops-config-backup` | Архів конфігів пристроїв у Git | `backup_config.py --device r1` |

Деталі — у відповідних `SKILL.md`.

## Структура репозиторію

```
.
├── AGENTS.md                   # системний промт агента
├── README.md                   # цей файл
├── .env.example                # шаблон env vars
├── .gitignore                  # виключає .env, backups/, __pycache__/, .cache/
├── requirements.txt            # Python-залежності
├── inventories/                # YAML host_vars для netdevops-config-render
├── templates/                  # Jinja2 шаблони конфігів
└── .agents/
    └── skills/                 # усі скіли у форматі agentskills.io
        └── <skill-name>/
            ├── SKILL.md        # YAML frontmatter + інструкції
            ├── scripts/        # виконувані скрипти
            └── references/     # додаткова документація
```

Кожен скіл самодостатній: має власний `SKILL.md` (YAML frontmatter з
`name` + `description`, потім інструкції), `scripts/` з виконуваними
скриптами та `references/` з додатковою документацією.

## Код-стайл та принципи

- **PEP 8**, type hints, `logging` замість `print` (крім фінального звіту CLI).
- **Read-only за замовчуванням** — запис у БД/пристрої потребує явного `--allow-write` / `yes`.
- **Сек'юрність** — секрети тільки в `.env` (gitignored) або у vault; жодних паролів у коді.
- **Структуроване логування** — JSON-логи з correlation ID.
- **Exit-коди**: `0` ok, `2` env/auth, `3` schema, `4` usage/not-found, `5` runtime.
- **Ідемпотентність** — повторні запуски не змінюють кінцевий стан.
- **Source of truth у Git** — конфігурації, схеми, плейбуки.
- **Dry-run перед apply** — diff, syntax check, smoke test.
- **Rollback plan** — кожна зміна має зворотний шлях.

## Troubleshooting

### `pymssql.OperationalError: ... connection refused`

- SQL Server не слухає на вказаному порту. Перевірте `DB_IP:1433` (або інший порт).
- Можливо, SQL Server слухає лише localhost, а ви підключаєтесь ззовні.
- Firewall блокує порт 1433.

### `pymssql.OperationalError: ... login failed`

- Неправильні `DB_USER` / `DB_PASSWORD` у `.env`.
- SQL Server не налаштований на mixed-mode authentication.
- Користувач не має прав на `CREATE DATABASE` (для першого запуску).

### `requests.exceptions.ConnectionError` (SWAPI)

- Немає інтернет-з'єднання.
- SWAPI тимчасово недоступний. Скіл `swapi-etl` має дисковий кеш у `.cache/`,
  але `swapi-fetch` кешує запити назавжди (до видалення `.cache/`).

### Кирилиця в Windows PowerShell

PowerShell 5.1 використовує cp1251. Усі скрипти перекодовують stdout → utf-8
всередині, але якщо бачите `?` замість кирилиці — додайте на початку скрипта:

```python
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
```

Або зберігайте у файл: `python script.py | Out-File -Encoding utf8 result.txt`.

### `ImportError: No module named 'pymssql'`

- venv не активований: `.\.venv\Scripts\Activate.ps1`.
- Залежності не встановлені: `pip install -r requirements.txt`.

### Таблиці вже існують, але з іншою схемою

- `IF OBJECT_ID(...) IS NULL` пропускає створення, якщо таблиця вже є.
- Рішення: `python .agents/skills/swapi-etl/scripts/swapi_etl.py drop --yes`
  а потім `init`.

## Додавання нового скілу

1. Обрати дієслівну назву в lowercase, що збігається з ім'ям папки.
2. Створити `.agents/skills/<name>/SKILL.md` (YAML frontmatter з `name` +
   `description` ≤ 1024 символів, потім інструкції). Тримати < 500 рядків;
   деталі виносити в `references/`.
3. Додати `scripts/` з виконуваними скриптами.
4. Описати *коли використовувати* і *коли НЕ використовувати*.
5. Задокументувати специфічні gotchas середовища.
6. Валідувати: `python -c "import ast; ast.parse(open(p).read())"` для всіх `.py`.
7. Запустити smoke-тест проти живого таргета (БД / API / пристрій).

## Ліцензія

Внутрішнє використання.

## Про документацію

Цей README сформульовано за допомогою AI-асистента **opencode**
(модель MiniMax-M3) у діалозі з автором репозиторію. Увесь код скілів,
ETL-логіка, схема БД та приклади — результат спільної роботи людини
та AI в рамках навчального проєкту.
