# Tank Savaşı — Android APK projesi

Bu klasör, verilen `tank_oyunu.py` oyununun Android'e uyarlanmış kaynak projesidir. `main.py` oyunun Python/Pygame kodunu içerir; Android yatay ekranda sol tarafta hareket joystick'i, sağ tarafta nişan + basılı tutarken ateş kontrolü vardır. Masaüstü klavye/fare kontrolleri korunur.

## En kolay yol: Google Colab derleyicisi

1. `TankSavasi_Android_Projesi.zip` dosyasını indir.
2. Ayrı verilen `TankSavasi_Android_APK_Yapici.ipynb` dosyasını Google Colab'a yükleyip aç: https://colab.research.google.com/
3. Not defterindeki tek kod hücresini çalıştır ve dosya seçme penceresinde `TankSavasi_Android_Projesi.zip` dosyasını seç.
4. Colab gerekli paketleri ve Android SDK/NDK araçlarını kurup `buildozer -v android debug` komutunu dener. İlk derleme büyük indirmeler yapabilir.
5. Başarılı olursa APK otomatik indirilmeye başlar.

**Dürüst not:** Bu paket bir APK değil, derleme projesidir. Bu çalışma ortamında internet erişimi olmadığı ve Android SDK/NDK kurulu olmadığı için APK burada üretilemedi. Pygame'in Android için derlenmesi, Buildozer/python-for-android sürümüne bağlıdır; derleme hatası çıkarsa tüm hata çıktısını sakla.

## Linux veya Windows + WSL2 ile derleme

Buildozer Linux/macOS ortamında çalışır. Windows kullanıcıları Ubuntu'yu WSL2'ye kurabilir.

```bash
sudo apt update
sudo apt install -y git zip unzip openjdk-17-jdk python3-pip python3-venv autoconf libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo6 cmake libffi-dev libssl-dev automake autopoint gettext
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install 'Cython<3.4' buildozer
buildozer -v android debug
```

Başarılı derleme sonrası APK `bin/` klasörüne çıkar.

## GitHub Actions seçeneği

Proje dosyalarını bir GitHub deposunun köküne koyup `main` veya `master` dalına gönder. `.github/workflows/build-android.yml` otomatik derlemeyi başlatır. İşlem başarılı olursa GitHub Actions sayfasındaki `Tank-Savasi-Android-APK` artifact'inden APK'yı indirebilirsin.

## Paket ayarları

- Uygulama adı: `Tank Savasi`
- Paket adı: `org.tanksavasi.tanksavasi`
- Ekran yönü: yatay
- Minimum Android API: 23
- Hedef Android API: 36
- İzinler: `INTERNET`, `ACCESS_NETWORK_STATE`

Play Store'a yüklemeden önce sana ait benzersiz bir paket kimliği, imzalama ve AAB hazırlığı gerekir. Çok oyunculu ağ işlevi gerçek Android cihazlarında ayrıca test edilmelidir.
