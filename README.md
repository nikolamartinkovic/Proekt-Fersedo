# Ферседо Проект

Flask апликација за производство, набавки, залихи, одмори, квалитет, понуди и состаноци.

## Брз старт

1. Инсталирај Python 3.11 или понов.
2. Креирај нов virtual environment.
3. Инсталирај ги зависностите од `requirements.txt`.
4. Копирај `.env.example` во `.env` и пополни ги вредностите.
5. Стартувај ја апликацијата.

## Windows команди

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
python run.py
```

## HTTPS локално

Ако сакаш апликацијата да стартува директно на `https://192.168.0.20`, намести во `.env`:

```env
APP_HOST=192.168.0.20
APP_PORT=443
APP_URL_SCHEME=https
PREFERRED_URL_SCHEME=https
HTTPS_CERT_PATH=192.168.0.20.pem
HTTPS_KEY_PATH=192.168.0.20-key.pem
```

Потоа стартувај со:

```powershell
python run.py
```

`run.py` автоматски ќе користи HTTPS ако `APP_URL_SCHEME=https` и ако постојат `192.168.0.20.pem` и `192.168.0.20-key.pem` во root на проектот.

## Конфигурација

Клучните вредности се во `.env`:

- `SECRET_KEY`
- `DATABASE_PATH`
- `VAPID_PUBLIC_KEY`
- `VAPID_PRIVATE_KEY`
- `VAPID_SUBJECT`
- `GROQ_API_KEY`
- `EMAIL_HOST`
- `EMAIL_PORT`
- `EMAIL_HOST_USER`
- `EMAIL_HOST_PASSWORD`
- `AUTO_ASSIGN_INTERVAL_SECONDS`
- `APP_HOST`
- `APP_PORT`
- `APP_URL_SCHEME`
- `PREFERRED_URL_SCHEME`
- `HTTPS_CERT_PATH`
- `HTTPS_KEY_PATH`
- `WAITRESS_THREADS`
- `APP_LOG_DIR`
- `APP_LOG_LEVEL`

## Забелешки

- Стариот `venv` во проектот е машински-зависен; користи нов `.venv`.
- `.env`, локалната база и генерираните upload фајлови не треба да се commit-ираат.
- `run.py` сега поддржува и HTTP и HTTPS старт според `.env`.
- Health check endpoint: `/health`
- Логовите по default одат во `instance/logs/app.log`
