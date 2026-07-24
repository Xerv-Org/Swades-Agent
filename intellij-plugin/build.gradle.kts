plugins {
    id("java")
    id("org.jetbrains.intellij.platform") version "2.1.0"
}

group = "com.xerv"
version = "1.0.0"

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

repositories {
    mavenCentral()
    intellijPlatform {
        defaultRepositories()
    }
}

dependencies {
    intellijPlatform {
        intellijIdeaCommunity("2023.3.4")
        bundledPlugin("org.jetbrains.plugins.terminal")
        instrumentationTools()
    }
}

intellijPlatform {
    pluginConfiguration {
        id.set("com.xerv.swades")
        name.set("Swades Agent")
        changeNotes.set("Initial release of Swades Agent IntelliJ integration.")
    }
}
