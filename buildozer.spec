[app]
# Tank Savasi Android paketi
# Play Store yayini icin package.domain degerini sana ait benzersiz bir adla degistir.
title = Tank Savasi
package.name = tanksavasi
package.domain = org.tanksavasi

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json,txt
version = 1.0.0

# Pygame oyunu yatay ekranda calisir.
orientation = landscape
fullscreen = 1

# Android icin pygame'in python-for-android recetesi kullanilir.
requirements = python3==3.11.9,hostpython3==3.11.9,pygame
p4a.bootstrap = sdl2
p4a.branch = develop

# Cok oyunculu LAN/TCP baglantisi icin.
android.permissions = INTERNET,ACCESS_NETWORK_STATE
android.minapi = 23
android.api = 36
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True

# Derlemeyi daha anlasilir tut.

[buildozer]
log_level = 2
warn_on_root = 0
