plugins {
    id("com.android.application")
    id("kotlin-android")
    // Flutter Gradle プラグインは Android / Kotlin の Gradle プラグインの後に適用する必要があります。
    id("dev.flutter.flutter-gradle-plugin")
}

android {
    namespace = "com.example.fishing_app"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }

    kotlinOptions {
        jvmTarget = JavaVersion.VERSION_11.toString()
    }

    defaultConfig {
        // TODO: 一意のアプリケーション ID を指定してください（https://developer.android.com/studio/build/application-id.html）。
        applicationId = "com.example.fishing_app"
        // 必要に応じて次の値をアプリに合わせて更新してください。
        // 詳細: https://flutter.dev/to/review-gradle-config
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    buildTypes {
        release {
            // TODO: リリースビルド用に独自の署名設定を追加してください。
            // 現状はデバッグ鍵で署名（`flutter run --release` が動作するようにするため）。
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}

flutter {
    source = "../.."
}
