# Fersedo Android

Ова е Android wrapper проект за постојната Flask web апликација.

## Што прави

- Ја отвора постојната HTTPS апликација во WebView
- Ги користи истите login, модули и backend функционалности
- Поддржува file picker, camera upload и download преку Android
- Има pull-to-refresh и основен error/retry екран

## Како да стартуваш

1. Отвори ја папката `android` во Android Studio.
2. Користи JDK 17, затоа што Android Gradle Plugin 8.x не работи со Java 8.
3. Дозволи Android Studio да ги симне Gradle зависностите.
4. Провери во [strings.xml](./app/src/main/res/values/strings.xml) дали `web_base_url` е точен.
5. Стартувај на Android уред што има пристап до `https://192.168.0.20`.

Алтернатива од терминал:

- `gradlew.bat assembleDebug`
- `gradlew.bat assembleRelease`

## Важно

- Во оваа прва верзија апликацијата е најбезбедна ако телефонот е на истата локална мрежа како серверот.
- За production е подобро HTTPS сертификатот да биде доверлив и валиден на Android уредот.
- Download-ите се праќаат преку Android DownloadManager и го носат session cookie за заштитени фајлови.
- Ако немаш `keystore.properties`, release build-от привремено паѓа на debug keystore за полесен интерен APK.
- Следен чекор е native поддршка за push notifications, background sync и подлабоки Android интеграции.
