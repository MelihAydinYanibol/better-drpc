# better-drpc

Kendi barındırdığınız medya sunucuları için Discord Rich Presence köprüsü.

`better-drpc`, aktif oturumlarınızı şu platformlardan sorgular:
- Jellyfin
- Plex
- Audiobookshelf

Ardından Discord aktivitenizi medya meta verileri, ilerleme durumu ve kapak görseli ile günceller.

## Özellikler

- Film, bölüm, müzik ve sesli kitaplar için canlı Discord Rich Presence güncellemeleri
- Çoklu sunucu sorgulama (Jellyfin, Plex, Audiobookshelf)
- Discord ile uyumlu kapak görseli URL'leri için otomatik görsel önbellekleme ve geçici görsel barındırma
- Birden fazla sunucu aktif olduğunda oturum önceliklendirmesi (en son aktif olan oturum gösterilir)
- Discord yeniden başlatıldığında veya RPC bağlantısı kesildiğinde temel Discord RPC yeniden bağlanma işlemi
- Tüm veya belirli sağlayıcılar için önbellek temizleme komutu

## Gereksinimler

- Python 3.8 veya üzeri
- Discord masaüstü uygulaması çalışıyor olmalı (RPC yalnızca yerel ağda çalışır)
- En az bir yapılandırılmış sunucu (Jellyfin, Plex veya Audiobookshelf)

## Kurulum

1. Depoyu klonlayın.
2. Sanal ortam oluşturun ve etkinleştirin.
3. Bağımlılıkları yükleyin.

```bash
pip install -r requirements.txt
```

## Yapılandırma

Proje kök dizininde bir `.env` dosyası oluşturun.

### Temel

- `CLIENT_ID` (zorunlu): `pypresence` tarafından kullanılan Discord uygulama istemci kimliği

### Jellyfin

- `JELLYFIN_SERVER_URL` (isteğe bağlı)
- `JELLYFIN_API_KEY` (isteğe bağlı)
- `JELLYFIN_USER` (isteğe bağlı, kullanıcı adına göre filtrele)

### Plex

- `PLEX_TOKEN` (isteğe bağlı)
- `PLEX_SERVER_NAME` (isteğe bağlı)
- `PLEX_USER` (isteğe bağlı, Plex kullanıcı adına göre filtrele)

### Audiobookshelf

- `AUDIOBOOKSHELF_SERVER_URL` (isteğe bağlı)
- `AUDIOBOOKSHELF_API_KEY` (isteğe bağlı)
- `AUDIOBOOKSHELF_USER` (isteğe bağlı, API isteğinde kullanıcı filtresi)

### Cihaz Filtresi

- `ONLY_GET_THIS_DEVICE` (isteğe bağlı, `true`/`false`)
	- Desteklendiğinde yalnızca mevcut makinenin ana bilgisayar adından gelen oturumları göstermek amacıyla tasarlanmıştır.

## Örnek `.env`

```env
CLIENT_ID=123456789012345678

JELLYFIN_SERVER_URL=http://192.168.1.20:8096
JELLYFIN_API_KEY=jellyfin_api_anahtariniz
JELLYFIN_USER=jellyfin_kullanici_adiniz

PLEX_TOKEN=plex_tokeniniz
PLEX_SERVER_NAME=PlexSunucunuz
PLEX_USER=plex_kullanici_adiniz

AUDIOBOOKSHELF_SERVER_URL=http://192.168.1.30:13378
AUDIOBOOKSHELF_API_KEY=abs_api_anahtariniz
AUDIOBOOKSHELF_USER=abs_kullanici_adiniz

ONLY_GET_THIS_DEVICE=false
```

## Kullanım

Uygulamayı başlatın:

```bash
python main.py
```

Yardım:

```bash
python main.py --help
```

Önbelleği temizle:

```bash
python main.py --clear-cache jellyfin
python main.py --clear-cache plex
python main.py --clear-cache abs
python main.py --clear-cache all
```

## Nasıl Çalışır

1. Her sağlayıcıda aktif oturumlar sorgulanır.
2. Duraklatılmış oturumlar atlanır.
3. Normalleştirilmiş bir medya yükü oluşturulur (`movie`, `episode`, `track`).
4. Kapak görseli önbelleğe alınır ve dışarıdan erişilebilir görsel URL'leri elde etmek için yüklenir.
5. Yük Discord Rich Presence'a gönderilir.

Birden fazla hizmet aktif olduğunda, en son aktif olan gösterilir.

## Proje Yapısı

- `main.py`: Uygulama döngüsü, sunucu arabuluculuğu, Discord RPC güncelleme/temizleme mantığı
- `djelly.py`: Jellyfin oturum sorgulama ve yük normalleştirme
- `dplex.py`: Plex oturum sorgulama ve yük normalleştirme
- `dabs.py`: Audiobookshelf oturum sorgulama ve yük normalleştirme
- `cache.py`: Görsel indirme/önbellekleme ve geçici URL yükleme yardımcısı
- `cache/`: Yerel önbellek dosyaları ve sağlayıcıya özgü önbellek dizinleri

## Notlar

- Discord Rich Presence görsel anahtarları herkese açık URL'ler gerektirir; bu proje kapak görselleri için geçici barındırılan URL'ler kullanır.
- Kapak görseli süresi dolarsa veya bozulursa `--clear-cache` kullanın ve yenilenmesini bekleyin.
- Discord kapalıysa, Discord masaüstü uygulaması tekrar açılana kadar güncellemeler başarısız olur.

## Sorun Giderme

- Durum güncellenmiyor:
	- Discord masaüstü uygulamasının çalıştığını doğrulayın.
	- `CLIENT_ID`'nin doğru olduğunu doğrulayın.
	- `.env` dosyasındaki sunucu kimlik bilgilerini/URL'lerini kontrol edin.
- Medya algılanmıyor:
	- Aktif olarak oynatma yaptığınızı (duraklatılmamış) doğrulayın.
	- Yapılandırılan kullanıcı filtrelerinin aktif oturum kullanıcınızla eşleştiğini doğrulayın.
- Yanlış/eski kapak görseli:
	- `--clear-cache <sağlayıcı>` veya `all` ile önbelleği temizleyin.

## Sorumluluk Reddi

Bu gayri resmi bir topluluk projesidir ve Discord, Plex, Jellyfin veya Audiobookshelf ile herhangi bir bağlantısı yoktur.
