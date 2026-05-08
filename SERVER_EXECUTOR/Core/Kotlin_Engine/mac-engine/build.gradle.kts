plugins {
    alias(libs.plugins.kotlin.jvm)
    alias(libs.plugins.kotlin.serialization)
    id("com.github.johnrengelman.shadow") version "8.1.1"
    application
}

kotlin {
    jvmToolchain(21)
}

application {
    mainClass = "com.kibot.macengine.MainKt"
}

dependencies {
    implementation(project(":packages:shared-models"))
    implementation(project(":packages:core"))
    implementation(project(":packages:ai-support"))
    implementation(project(":packages:control-plane"))
    implementation(project(":packages:indodax-client"))
    implementation(project(":packages:binance-client"))

    implementation(libs.kotlinx.coroutines.core)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.kotlinx.datetime)
    implementation(libs.ktor.server.core)
    implementation(libs.ktor.server.cio)
    implementation(libs.ktor.server.content.negotiation)
    implementation(libs.ktor.server.call.logging)
    implementation(libs.ktor.server.status.pages)
    implementation(libs.ktor.server.websockets)
    implementation(libs.ktor.server.html.builder)
    implementation(libs.ktor.serialization.kotlinx.json)
    implementation(libs.slf4j.api)
    implementation(libs.jmdns)
    runtimeOnly(libs.logback.classic)

    testImplementation(libs.junit.jupiter)
    testImplementation(kotlin("test"))
    testImplementation(project(":packages:test-kit"))
}

tasks.test {
    useJUnitPlatform()
}

tasks.named<com.github.jengelman.gradle.plugins.shadow.tasks.ShadowJar>("shadowJar") {
    archiveClassifier.set("all")
    mergeServiceFiles()
    manifest {
        attributes(
            "Implementation-Title" to "KiCryp Mac Engine",
            "Implementation-Version" to project.version,
            "Main-Class" to "com.kibot.macengine.MainKt",
        )
    }
}

tasks.register("fatJar") {
    group = "build"
    description = "Assemble fat JAR via shadowJar for stable runtime dependencies."
    dependsOn(tasks.named("shadowJar"))
}

tasks.register("fatJarCopy") {
    dependsOn("fatJar")
    doLast {
        copy {
            from(tasks.named("fatJar"))
            into(file("../"))
        }
    }
}
