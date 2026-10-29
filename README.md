# Maç Analiz

Günün bülteni için istatistik modeliyle maç analizi yapan ve sonuçları telefondan açılan bir sayfada gösteren sistem. Yapay zeka kullanmaz, ücretli API kullanmaz. Her gün GitHub üzerinde kendiliğinden çalışır.

## Ne yapar?

Her sabah 09:17'de ve öğleden sonra 16:17'de (Türkiye saati):

1. Takip edilen liglerin bu ve geçen sezonki tüm maçlarını indirir (football-data.co.uk).
2. Günün ve yarının lig fikstürünü oranlarıyla birlikte, kupa ve UEFA maçlarını da ClubElo'dan alır.
3. Her maç için modeli çalıştırır ve raporu `docs/data/latest.json` dosyasına yazar.
4. Telefondaki sayfa bu dosyayı okur.

## Model nasıl çalışır?

| Bölüm | Yöntem |
|---|---|
| Gol, 1X2, KG, Üst/Alt, İY | Dixon-Coles Poisson modeli. Takım başına hücum ve savunma gücü, ev sahibi avantajı ve zaman ağırlığı (yakın maçlar daha etkili). |
| Kupa / UEFA maçları | Elo gücü (ClubElo) ile takımların lig gol profili birleştirilir. |
| Korner, şut, isabetli şut | Lig ortalaması × takımın üretme katsayısı × rakibin izin verme katsayısı. Dağılım lig verisinden ölçülür. |
| Kart | Aynı model, üstüne hakem katsayısı (hakem verisi olan liglerde), derbi ve kupa çarpanı. |
| Değer | Model olasılığı × oran − 1. +%4 ve üstü "değerli" sayılır. |
| Model testi | `backtest.py` geçmiş 30 haftayı, geleceği görmeden yeniden tahmin eder. İsabet ve değerli bahislerin ROI'si hesaplanır. |

## Takip edilen ligler

Süper Lig, Premier Lig, Championship, La Liga 1-2, Serie A-B, Bundesliga 1-2, Ligue 1-2, Eredivisie, Portekiz, Belçika, Yunanistan, İskoçya. Ayrıca bu liglerdeki takımların ulusal kupa ve UEFA maçları da alınır. İki takımı da bu liglerin dışında olan maçlar atlanır.

Lig eklemek ya da çıkarmak için `src/config.py` içindeki `LEAGUES` listesini düzenle.

## Kurulum (bir kerelik, yaklaşık 5 dakika)

1. GitHub'da yeni bir repo aç, adı örneğin `mac-analiz` olsun. Ücretsiz hesapta Pages için repo **Public** olmalı.
2. Bu klasördeki her şeyi repoya yükle. `.github` klasörü dahil, gizli klasörü unutma.
3. Repo → **Settings → Pages**: Source = *Deploy from a branch*, Branch = `main`, klasör = `/docs` → Save.
4. Repo → **Settings → Actions → General → Workflow permissions**: *Read and write permissions* seç → Save.
5. Repo → **Actions** sekmesi → *Günlük analiz* → **Run workflow** ile ilk çalıştırmayı elle başlat. 2-4 dakika sürer.
6. Telefondan `https://KULLANICIADIN.github.io/mac-analiz/` adresini aç.
   - iPhone: Safari → Paylaş → **Ana Ekrana Ekle**
   - Android: Chrome → ⋮ → **Ana ekrana ekle**

Bundan sonra her gün kendiliğinden güncellenir.

## Bilgisayarda deneme

```bash
pip install -r requirements.txt
python src/run.py              # gerçek veriyle
python src/backtest.py --offline
cd docs && python -m http.server 8000   # tarayıcıda localhost:8000
```

İnternetsiz test için: `python tests/make_fake_data.py && python src/run.py --offline --date 2026-10-29`

## Bilinmesi gerekenler

- **Hakem verisi** ücretsiz kaynakta yalnızca İngiltere liglerinde var. Diğer liglerde kart beklentisi takım ve lig verisine dayanır, raporda bu yazar.
- **Oyuncu verisi** (sakatlık, ceza, bireysel şut) ücretsiz kaynakta yok. Analiz takım düzeyindedir.
- **Oranlar** football-data'daki Avrupa bahis şirketlerinin ortalamasıdır, iddaa oranı değildir. Korner ve kart için oran yok. Bu pazarlarda "adil oran" gösterilir; iddaa oranı bundan yüksekse değerli demektir.
- **Kupa maçlarında** saat bilgisi ve oran yoktur. Form verisi yalnızca lig maçlarından gelir.
- Takım adı eşleşmezse `src/run.py` içindeki `ALIASES` sözlüğüne ekle (ClubElo adı → football-data adı).
- Hiçbir model kazanç garantisi vermez. "Model Testi" sekmesindeki ROI'ye bakmadan büyük oynama.
