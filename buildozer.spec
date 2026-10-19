[app]
android.ndk = 25b
source.dir = .
main.filename = tank_oyunu.py
title = Tank Savasi
package.name = tanksavasi
package.domain = org.tanksavasi
source.include_exts = py,png,jpg,kv,atlas,ico
version = 1.0
requirements = python3,pygame
orientation = landscape
fullscreen = 1
android.permissions = INTERNET

[buildozer]
log_level = 2
warn_on_root = 1