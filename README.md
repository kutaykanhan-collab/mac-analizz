# Maç Analiz

Günün bülteni için istatistik modeliyle maç analizi yapan ve sonuçları telefondan açılan bir sayfada gösteren sistem. Yapay zeka kullanmaz, ücretli API kullanmaz. Her gün GitHub üzerinde kendiliğinden çalışır.

## Ne yapar?

Her sabah 09:17'de ve öğleden sonra 16:17'de (Türkiye saati):

1. Takip edilen liglerin bu ve geçen sezonki tüm maçlarını indirir (football-data.co.uk).
2. Günün bültenini **Maçkolik**'ten alır: lig, Ziraat Türkiye Kupası, Lig Kupası, Kral Kupası, KNVB vb. ve iddaa 1-X-2 oranları. Lig fikstürü ve Avrupa oranları football-data'dan, UEFA fikstürü fixturedownload.com'dan gelir.
3. Her maç için modeli çalıştırır ve raporu `docs/data/latest.json` dosyasına yazar.
4. Telefondaki sayfa bu dosyayı okur.

## Model nasıl çalışır?

| Bölüm | Yöntem |
|---|---|
| Gol, 1X2, KG, Üst/Alt, İY | Dixon-Coles Poisson modeli. Takım başına hücum ve savunma gücü, ev sahibi avantajı ve zaman ağırlığı (yakın maçlar daha etkili). |
| Gol modeli girdisi | %50 gerçek gol + %50 isabetli şuttan beklenen gol. Geçmiş testte saf golden isabetli çıktı. |
| Nihai olasılık | Oran varsa %25 model + %75 piyasa. Geçmiş testte en isabetli karışım bu. Oran yoksa saf model kullanılır. |
| UEFA maçları | Lig gücü düzeltmeli gol modeli. ClubElo puanı alınabilirse güç farkını Elo belirler. |
| Korner, şut, isabetli şut | Lig ortalaması × takımın üretme katsayısı × rakibin izin verme katsayısı. Dağılım lig verisinden ölçülür. |
| Kart | Aynı model, üstüne hakem katsayısı (hakem verisi olan liglerde), derbi ve kupa çarpanı. |
| Model farkı | Model olasılığı × oran − 1 ≥ %4. Geçmiş testte bu sinyal **kârsız** çıktı (ROI yaklaşık −%10); bilgi amaçlı gösterilir. |
| Model testi | `backtest.py` geçmiş 30 haftayı, geleceği görmeden yeniden tahmin eder. İsabet ve değerli bahislerin ROI'si hesaplanır. |

## Takip edilen ligler

Süper Lig, Premier Lig, Championship, La Liga 1-2, Serie A-B, Bundesliga 1-2, Ligue 1-2, Eredivisie, Portekiz, Belçika, Yunanistan, İskoçya. Ayrıca bu liglerdeki takımların UEFA maçları (Şampiyonlar, Avrupa, Konferans Ligi) da alınır. Bu ülkelerin ulusal kupaları da Maçkolik bülteninden gelir. Kupada alt lig rakibinin verisi yoksa gücü alt lig ortalaması kabul edilir; iki takımın da verisi yoksa maç sayfanın altında "analiz edilemeyen" listesinde görünür. İki takımı da bu liglerin dışında olan maçlar atlanır.

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

İnternetsiz test için: `python src/run.py --offline  (repodaki data/raw ile)`

## Bilinmesi gerekenler

- **Hakem verisi** ücretsiz kaynakta yalnızca İngiltere liglerinde var. Diğer liglerde kart beklentisi takım ve lig verisine dayanır, raporda bu yazar.
- **Oyuncu verisi** (sakatlık, ceza, bireysel şut) ücretsiz kaynakta yok. Analiz takım düzeyindedir.
- **Oranlar** football-data'daki Avrupa bahis şirketlerinin ortalamasıdır, iddaa oranı değildir. Korner ve kart için oran yok. Bu pazarlarda "adil oran" gösterilir; iddaa oranı bundan yüksekse değerli demektir.
- **Kupa ve UEFA maçlarında** iddaa 1-X-2 oranı kullanılır; korner, kart ve şut için oran yoktur. Form verisi yalnızca lig maçlarından gelir.
- football-data fikstür dosyası birkaç gün ileriyi gösterir. Hafta sonu maçları genelde Perşembe-Cuma eklenir.
- Takım adı eşleşmezse `src/names.py` içindeki `ALIASES` sözlüğüne ekle (diğer kaynaktaki ad → football-data adı).
- Hiçbir model kazanç garantisi vermez. "Model Testi" sekmesi modelin geçmiş başarısını dürüstçe gösterir; ona bakmadan büyük oynama.

## Canlı sekme

Telefon, FotMob'dan her 60 saniyede canlı veri çeker ve şu ihtimalleri hesaplar: maçta yeni gol, sonraki 10 dakikada gol, sonraki golü kim atar, şu anki skora göre maç sonucu ve Üst. Hesap telefonda yapılır, GitHub'ı beklemez.

Model (src/live_model.py ve docs/canli.js, aynı formül):
- Maç öncesi gol beklentisi (bültendeki analizden) kalan süreye yayılır. Gol hızı maçın sonlarına doğru artar, uzatma süresi de hesaba girer.
- Takımın xG temposu, maç öncesi beklentiyle harmanlanır.
- Geride olan takımın temposu artar. Kırmızı kart, eksik kalanın temposunu düşürür, rakibinkini artırır.
- Son 10 dakikanın baskısı (momentum), sonraki 10 dakikayı etkiler.

`src/live_backtest.py` geçmiş maçlarda modeli test eder ve ayarları `docs/data/live_params.json` dosyasına yazar. "Canlı model verisi" iş akışı her pazartesi yeni maçları ekleyip testi yeniler.
