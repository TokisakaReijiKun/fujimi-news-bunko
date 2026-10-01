plugins {
    id("com.android.application")
}

layout.buildDirectory.set(gradle.gradleUserHomeDir.resolve("fujimi-android-build/app"))

android {
    namespace = "jp.fujimi.newsbunko.next"
    compileSdk = 36

    defaultConfig {
        applicationId = "jp.fujimi.newsbunko.next"
        minSdk = 29
        targetSdk = 35
        versionCode = 3
        versionName = "1.0.2"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    val signingFile = providers.environmentVariable("FUJIMI_ANDROID_KEYSTORE").orNull
    if (signingFile != null) {
        signingConfigs.create("localRelease") {
            storeFile = file(signingFile)
            storePassword = providers.environmentVariable("FUJIMI_ANDROID_STORE_PASSWORD").get()
            keyAlias = "fujimi-next"
            keyPassword = providers.environmentVariable("FUJIMI_ANDROID_KEY_PASSWORD").get()
        }
        buildTypes.getByName("release").signingConfig = signingConfigs.getByName("localRelease")
    }

    packaging {
        resources.excludes += setOf("META-INF/CONTRIBUTORS.md", "META-INF/LICENSE", "META-INF/LICENSE.md", "META-INF/NOTICE")
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    sourceSets.getByName("main").assets.srcDir(layout.buildDirectory.get().asFile.resolve("generated/assets"))

}

dependencies {
    implementation(project(":core"))
    implementation("androidx.webkit:webkit:1.16.0")
    implementation("androidx.media3:media3-exoplayer:1.11.0")
    implementation("androidx.media3:media3-session:1.11.0")
    implementation("androidx.work:work-runtime:2.12.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.jsoup:jsoup:1.21.2")
    implementation("com.atilika.kuromoji:kuromoji-ipadic:0.9.0")
    androidTestImplementation("androidx.test:core:1.7.0")
    androidTestImplementation("androidx.test:runner:1.7.0")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
}

val prepareAppAssets by tasks.registering(Copy::class) {
    from(rootProject.projectDir.parentFile.resolve("static")) {
        into("static")
        exclude("library-layout-preview.html")
    }
    from(rootProject.projectDir.parentFile.resolve("apk-original/dictionary/dictionary.sqlite3")) {
        into("dictionary")
    }
    into(layout.buildDirectory.dir("generated/assets"))
}

val prepareAppIcon by tasks.registering(Copy::class) {
    from(rootProject.projectDir.parentFile.resolve("assets/desktop-icon.png")) {
        rename { "ic_launcher.png" }
    }
    into(layout.buildDirectory.dir("generated/app-icon/drawable-nodpi"))
}

android.sourceSets.getByName("main").res.srcDir(layout.buildDirectory.get().asFile.resolve("generated/app-icon"))

tasks.named("preBuild") {
    dependsOn(prepareAppAssets, prepareAppIcon)
}

tasks.register("printDebugArtifact") {
    dependsOn("assembleDebug")
    doLast {
        println(layout.buildDirectory.get().asFile.resolve("outputs/apk/debug/app-debug.apk"))
    }
}
