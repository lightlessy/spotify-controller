# Spotify Snap Control

Windows'ta parmak şıklatmasıyla Spotify masaüstü uygulamasını kontrol eder.

- **Tek şıklatma:** sonraki şarkı
- **Çift şıklatma:** önceki şarkı
- Spotify duraklatılmışsa veya kapalıysa komut göndermez.
- Başarılı algılamadan sonra Windows bildirimi gösterir.
- **Hatalı algılamaydı** düğmesi ilgili ses örneğini yerel yanlış-pozitif verisine ekler.
- Spotify hesabı veya API anahtarı istemez.

## Nasıl algılıyor?

Uygulama artık yalnızca sabit ses eşiklerine güvenmez:

1. Geniş bir transient dedektörü olası kısa sesleri aday olarak toplar.
2. Adayın çevresindeki yaklaşık 180 ms ses penceresinden zamansal ve spektral özellikler çıkarılır.
3. `calibrate.bat` sırasında senin şıklatmaların; konuşma ve klavye seslerine karşı öğrenilir.
4. Yerel k-en-yakın-komşu doğrulayıcı yalnızca şıklatmaya benzeyen adayları kabul eder.
5. Mikrofon açılışındaki pop seslerini elemek için ilk 1,8 saniye yok sayılır.

Model, kayıt ve özellikler hiçbir sunucuya gönderilmez.

## Kurulum

### 1. Repoyu indir

```powershell
git clone https://github.com/lightlessy/spotify-controller.git
cd spotify-controller
```

### 2. `install.bat` çalıştır

Kurucu Python ortamını oluşturur, paketleri yükler, mikrofonu ve Windows medya kontrolünü test eder; feedback bildirim protokolünü kaydeder.

### 3. `calibrate.bat` çalıştır

Kalibrasyon iki kısa kayıt alır:

- 12 net parmak şıklatması
- Normal konuşma ve klavye kullanımı

Bittiğinde kişisel model `snap_model.json` olarak kaydedilir. Bu dosya `.gitignore` içindedir.

## Çalıştırma

- Görünür test: **`start.bat`**
- Sessiz arka plan: **`start-hidden.vbs`**
- Ayrıntılı ölçümler: **`debug.bat`**
- Kapatma: **`stop.bat`**
- Yeniden kalibrasyon: **`calibrate.bat`**

Aynı anda yalnızca bir kopya çalışabilir.

## Güncelleme

```powershell
git pull
```

Algılama modeli değiştiyse `calibrate.bat` dosyasını yeniden çalıştır.

## Feedback

Spotify komutu başarıyla uygulandığında bildirimde **Hatalı algılamaydı** düğmesi görünür. Düğmeye basıldığında ilgili kayıt şuraya taşınır:

```text
training_data/
└── false_positives/
    ├── manifest.csv
    ├── <event_id>.wav
    └── <event_id>.json
```

Geçici kayıtlar `training_data/pending/` altında tutulur ve varsayılan olarak sonraki temizlikte 24 saatten eskiyse silinir. Feedback verisi henüz modeli otomatik yeniden eğitmez.

Kalibrasyon kayıtları:

```text
training_data/calibration/
├── <tarih>-snaps.wav
├── <tarih>-negatives.wav
└── <tarih>-summary.json
```

`training_data/` ve `snap_model.json` Git'e dahil edilmez.

## Farklı mikrofon seçme

1. `list-microphones.bat` çalıştır.
2. Mikrofon ID'sini bul.
3. `config.json` içindeki `input_device` değerini değiştir.
4. Mikrofon değişince `calibrate.bat` ile yeniden kalibre et.

Örnek:

```json
"input_device": 15
```

## Çift şıklatma gecikmesi

Tek şıklatma komutu, ikinci şıklatma ihtimali için varsayılan olarak yaklaşık `0.48` saniye bekler. Bu süre `config.json` içindeki `double_snap_window` ile değiştirilebilir.

## Bildirim ayarları

`feedback_config.json`:

```json
{
  "notifications_enabled": true,
  "capture_seconds": 1.5,
  "pending_retention_hours": 24
}
```

## Windows başlangıcı

- Başlangıca ekle: `startup-enable.bat`
- Başlangıçtan kaldır: `startup-disable.bat`

Önce görünür modda yeterince test edip ardından başlangıca ekle.

## Sorun giderme

### Kişisel model bulunamadı

`calibrate.bat` çalıştır.

### Mikrofon değişti veya masa düzeni değişti

Kalibrasyonu tekrarla. Model mikrofona, mesafeye, şıklatma biçimine ve klavyenin akustik karakterine özeldir.

### Bildirim düğmesi çalışmıyor

`install.bat` dosyasını yeniden çalıştır.

### Mikrofon açılamadı

Windows'ta **Ayarlar > Gizlilik ve güvenlik > Mikrofon** bölümünde mikrofon ve masaüstü uygulaması erişimini aç.

### Spotify bulunamadı

Spotify masaüstü uygulamasını açıp şarkı çal. Web oynatıcı hedeflenmez.

## Gereksinimler

- Windows 10 veya 11
- Mikrofon
- Spotify masaüstü uygulaması
- Python 3.11+

## Lisans

MIT
