# Spotify Snap Control

Windows'ta parmak şıklatmasıyla Spotify masaüstü uygulamasını kontrol eder.

- **Tek şıklatma:** sonraki şarkı
- **Çift şıklatma:** önceki şarkı
- Spotify duraklatılmışsa veya kapalıysa hiçbir komut göndermez.
- Spotify hesabı, API anahtarı veya tarayıcı eklentisi istemez.

## Kurulum

### 1. Repoyu indir

```powershell
git clone https://github.com/lightlessy/spotify-controller.git
cd spotify-controller
```

Git kullanmıyorsan GitHub'da **Code > Download ZIP** ile indirip klasörü çıkartabilirsin.

### 2. `install.bat` dosyasına çift tıkla

Kurucu:

1. Gerekirse Python 3.12'yi `winget` ile kurar.
2. Projeye özel `.venv` oluşturur.
3. Gerekli paketleri yükler.
4. Mikrofon ve Windows medya kontrolünü test eder.
5. İstersen programı Windows başlangıcına ekler.

### 3. Çalıştır

- Arka planda sessiz çalıştırmak için: **`start-hidden.vbs`**
- Konsolu ve algılama mesajlarını görmek için: **`start.bat`**
- Ayrıntılı ses değerlerini görmek için: **`debug.bat`**

Aynı anda yalnızca bir kopya çalışabilir.

## Hassasiyet ayarı

`config.json` dosyasını Not Defteri ile aç.

Yanlışlıkla davul, alkış veya masa tıklamasını şıklatma sanıyorsa:

```json
"min_peak": 0.06,
"min_high_frequency_ratio": 0.4
```

Şıklatmanı algılamıyorsa:

```json
"min_rms": 0.004,
"min_peak": 0.03
```

Tek şıklatmadan sonra komut gecikmesi, çift şıklatma ihtimalini beklemek için varsayılan olarak yaklaşık `0.48` saniyedir. Bunu `double_snap_window` ile değiştirebilirsin.

## Farklı mikrofon seçme

1. `list-microphones.bat` dosyasını çalıştır.
2. Kullanmak istediğin mikrofonun başındaki sayıyı bul.
3. `config.json` içindeki `input_device` değerini o sayı yap:

```json
"input_device": 3
```

Varsayılan Windows mikrofonunu kullanmak için değer `null` kalmalı.

## Windows başlangıcı

- Başlangıca ekle: `startup-enable.bat`
- Başlangıçtan kaldır: `startup-disable.bat`

## Sorun giderme

### Mikrofon açılamadı

Windows'ta **Ayarlar > Gizlilik ve güvenlik > Mikrofon** bölümüne girip:

- Mikrofon erişimini aç.
- “Masaüstü uygulamalarının mikrofonunuza erişmesine izin ver” seçeneğini aç.

Ardından `test.bat` çalıştır.

### Spotify bulunamadı

Spotify masaüstü uygulamasını açıp bir şarkı çal. Web tarayıcısındaki Spotify sekmesi hedeflenmez; uygulama özellikle Spotify'ın Windows medya oturumunu arar.

### Çok fazla yanlış algılama var

Mümkünse kulaklık kullan. Hoparlörden gelen sert hi-hat ve clap sesleri akustik olarak parmak şıklatmasına benzeyebilir. `min_peak` ve `min_high_frequency_ratio` değerlerini artır.

### Programı tamamen kapatma

Görev Yöneticisi'nde `pythonw.exe` işlemini sonlandır veya oturumu kapat. Konsoldan `start.bat` ile çalıştırdıysan `Ctrl+C` yeterlidir.

## Nasıl çalışıyor?

Mikrofondan kısa ses blokları alır; ani tepe şiddeti, RMS, crest factor ve yüksek frekans enerji oranını ölçer. Eşiklere uyan kısa darbeleri şıklatma sayar. Ardından Windows `GlobalSystemMediaTransportControlsSessionManager` üzerinden yalnızca Spotify oturumuna `skip next` veya `skip previous` komutu gönderir.

## Gereksinimler

- Windows 10 veya 11
- Çalışan bir mikrofon
- Spotify masaüstü uygulaması
- Python 3.11+ (`install.bat`, yoksa Python 3.12 kurmayı dener)

## Lisans

MIT
