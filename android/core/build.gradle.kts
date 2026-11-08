plugins {
    id("org.jetbrains.kotlin.jvm")
}

layout.buildDirectory.set(gradle.gradleUserHomeDir.resolve("fujimi-android-build/core"))

kotlin {
    jvmToolchain(21)
    compilerOptions.jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
}

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

dependencies {
    implementation("com.atilika.kuromoji:kuromoji-ipadic:0.9.0")
    implementation("org.jsoup:jsoup:1.21.2")
    implementation("org.json:json:20250517")
    testImplementation(kotlin("test"))
    testImplementation("org.junit.jupiter:junit-jupiter:5.12.2")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")
}

tasks.test {
    useJUnitPlatform()
}
