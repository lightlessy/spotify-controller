# Spotify Snap Control

Windows'ta parmak şıklatmasıyla Spotify masaüstü uygulamasını kontrol eder.

- **Tek şıklatma:** sonraki şarkı
- **Çift şıklatma:** önceki şarkı
- Spotify duraklatılmışsa veya kapalıysa hiçbir komut göndermez.
- Her başarılı algılamadan sonra modern bir Windows bildirimi gösterir.
- Bildirimdeki **Hatalı algılamaydı** düğmesi, ilgili ses örneğini yanlış-pozitif eğitim verisine ekler.
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
5. Bildirimdeki feedback düğmesi için `spotify-snap://` protokolünü kullanıcı hesabına kaydeder.
6. İstersen programı Windows başlangıcına ekler.

### Mevcut kurulumu güncelleme

```powershell
cd spotify-controller
git pull
```

Ardından **`install.bat` dosyasını yeniden çalıştır**. Yeni bildirim paketi kurulur ve feedback düğmesi Windows'a kaydedilir.

## Çalıştırma

- Arka planda sessiz çalıştırmak için: **`start-hidden.vbs`**
- Konsolu ve algılama mesajlarını görmek için: **`start.bat`**
- Programı tamamen kapatmak için: **`stop.bat`**
- Ayrıntılı ses değerlerini görmek için: **`debug.bat`**

Aynı anda yalnızca bir kopya çalışabilir.

## Feedback nasıl çalışıyor?

Spotify komutu başarıyla uygulandığında bir Windows bildirimi gelir:

- Bildirim hangi komutun çalıştığını söyler.
- **Hatalı algılamaydı** düğmesi bulunur.
- Her bildirim kendi algılama kimliğini taşır. Eski bir bildirime bassan bile doğru ses örneği etiketlenir.

Düğmeye bastığında ilgili kayıt şuraya taşınır:

```text
training_data/
└── false_positives/
    ├── manifest.csv
    ├── <event_id>.wav
    └── <event_id>.json
```

- `.wav`: yaklaşık son 1,5 saniyelik mikrofon sesi
- `.json`: eşik ölçümleri, tek/çift şıklatma bilgisi ve uygulanan komut
- `manifest.csv`: model eğitiminde kolayca okunabilecek toplu indeks
- Etiket: `false_positive`

Bu özellik **henüz modeli otomatik olarak yeniden eğitmez**; temiz ve düzenli eğitim verisi biriktirir. Sonraki aşamada bu veriyle kişisel bir sınıflandırıcı eğitilebilir.

## Gizlilik

- Ses verisi hiçbir sunucuya gönderilmez.
- Kayıtlar yalnızca bilgisayarındaki repo klasöründe tutulur.
- Bir komut algılandığında ses önce `training_data/pending/` altında geçici tutulur.
- Feedback düğmesine basılmazsa geçici kayıt varsayılan olarak 24 saat sonra silinir.
- `training_data/` `.gitignore` içindedir; yanlışlıkla GitHub'a push edilmez.

## Feedback ayarları

`feedback_config.json` dosyasını Not Defteri ile açabilirsin:

```json
{
  "notifications_enabled": true,
  "capture_seconds": 1.5,
  "pending_retention_hours": 24
}
```

- Bildirimleri kapatmak için `notifications_enabled` değerini `false` yap.
- Kaydedilen ses penceresini `capture_seconds` ile değiştir.
- Geçici kayıtların kaç saat tutulacağını `pending_retention_hours` ile değiştir.

## Algılama hassasiyeti

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

### Bildirim geliyor ama düğme çalışmıyor

`install.bat` dosyasını yeniden çalıştır. Kurucu `spotify-snap://` feedback protokolünü tekrar kaydeder.

### Mikrofon açılamadı

Windows'ta **Ayarlar > Gizlilik ve güvenlik > Mikrofon** bölümüne girip:

- Mikrofon erişimini aç.
- “Masaüstü uygulamalarının mikrofonunuza erişmesine izin ver” seçeneğini aç.

Ardından `test.bat` çalıştır.

### Spotify bulunamadı

Spotify masaüstü uygulamasını açıp bir şarkı çal. Web tarayıcısındaki Spotify sekmesi hedeflenmez; uygulama özellikle Spotify'ın Windows medya oturumunu arar.

### Çok fazla yanlış algılama var

Mümkünse kulaklık kullan. Hoparlörden gelen sert hi-hat ve clap sesleri akustik olarak parmak şıklatmasına benzeyebilir. `min_peak` ve `min_high_frequency_ratio` değerlerini artır.

## Gereksinimler

- Windows 10 veya 11
- Çalışan bir mikrofon
- Spotify masaüstü uygulaması
- Python 3.11+ (`install.bat`, yoksa Python 3.12 kurmayı dener)

## Lisans

MIT
