"""Initial legal-document drafts. These texts require company-specific legal review before publication."""


TOKENS_HELP = (
    "Kullanılabilir alanlar: [[COMPANY_NAME]], [[BRAND_NAME]], [[ADDRESS]], [[TAX_OFFICE]], "
    "[[TAX_NUMBER]], [[MERSIS_NUMBER]], [[KEP_ADDRESS]], [[SUPPORT_EMAIL]], [[KVKK_EMAIL]], "
    "[[PHONE]], [[SLA_TARGET]] ve [[EFFECTIVE_DATE]]."
)


def _sections(*items):
    return "".join(f"<h2>{heading}</h2><p>{body}</p>" for heading, body in items)


COMMON_PARTIES = (
    "Hizmet sağlayıcı: <strong>[[COMPANY_NAME]]</strong> (marka: [[BRAND_NAME]]), adres: "
    "[[ADDRESS]], e-posta: [[SUPPORT_EMAIL]], telefon: [[PHONE]], vergi dairesi/no: "
    "[[TAX_OFFICE]] / [[TAX_NUMBER]], MERSİS: [[MERSIS_NUMBER]], KEP: [[KEP_ADDRESS]]."
)


LEGAL_DOCUMENTS = [
    {
        "slug": "mesafeli-satis-sozlesmesi",
        "title": "Mesafeli Satış Sözleşmesi",
        "category": "sales",
        "summary": "ReklamAnaliz.net üzerinden uzaktan kurulan ücretli hizmet sözleşmesinin koşulları.",
        "requires_acceptance": True,
        "content": _sections(
            ("1. Taraflar", COMMON_PARTIES + " Alıcı; sipariş ekranında adı, iletişim ve fatura bilgileri bulunan tüketici veya ticari müşteridir."),
            ("2. Konu ve kapsam", "Bu sözleşme, alıcının seçtiği abonelik, AI kredisi veya ürün araştırma hakkının elektronik ortamda sağlanmasına ilişkin tarafların hak ve yükümlülüklerini düzenler. Sipariş özeti, plan kapsamı, süre, vergi ve toplam bedel sözleşmenin ayrılmaz parçasıdır."),
            ("3. Sözleşmenin kurulması", "Alıcı ön bilgilendirme formunu ve sözleşmeyi okuyup ödeme yükümlülüğü doğuran siparişi açıkça onayladığında sözleşme kurulur. Onay ve sözleşme kaydı kalıcı veri saklayıcısıyla alıcıya iletilebilir ve işlem kayıtları saklanır."),
            ("4. Hizmetin ifası", "Abonelik hakları başarılı kart işlemi sonrasında, havale/EFT işlemlerinde ise ödemenin doğrulanmasından sonra hesaba tanımlanır. Ücretsiz deneme süresi ücretli hizmetten ayrıdır ve kendiliğinden ücret tahsilatı yapılmadıkça ödeme borcu doğurmaz."),
            ("5. Bedel ve ödeme", "Tüm vergiler dahil toplam bedel sipariş ekranında gösterilir. Banka veya ödeme kuruluşunun uyguladığı kullanıcı kaynaklı ücretlerden sağlayıcı sorumlu değildir. Fatura, alıcının bildirdiği bilgilerle elektronik olarak düzenlenir."),
            ("6. Cayma hakkı", "Tüketici, hizmet sözleşmesinin kurulmasından itibaren on dört gün içinde gerekçe göstermeden cayabilir. Cayma bildirimi [[SUPPORT_EMAIL]] adresine veya sunulan kalıcı veri saklayıcısına yöneltilir. Tüketicinin açık talebi ve onayıyla cayma süresi dolmadan tamamen ifa edilen hizmetlerde ya da elektronik ortamda anında teslim edilip kullanılmaya başlanan dijital haklarda mevzuattaki istisnalar uygulanabilir. Kullanılmamış kısma ilişkin emredici tüketici hakları saklıdır."),
            ("7. İade", "Geçerli cayma veya haklı fesih halinde iade, bildirimin ulaşmasından sonra mevzuattaki süre içinde ve kural olarak ödeme aracına uygun biçimde yapılır. Ücretsiz deneme ayrıca bir iade taahhüdü oluşturmaz. Kullanılmış ek kredi veya araştırma hakları, hukuken zorunlu olmadıkça yeniden kullanıma açılamaz."),
            ("8. Sorumluluk ve üçüncü taraflar", "Meta, Google, TikTok, LinkedIn ve diğer platformların API erişimi, kesintileri veya politika değişiklikleri sağlayıcının doğrudan kontrolü dışındadır. Sağlayıcı kendi kusurundan doğan sorumluluğunu emredici mevzuat sınırları içinde yerine getirir; tüketicinin yasal hakları sınırlandırılmaz."),
            ("9. Başvuru ve uyuşmazlık", "Talepler [[SUPPORT_EMAIL]] adresine iletilebilir. Tüketiciler, yürürlükteki parasal sınırlar çerçevesinde tüketici hakem heyeti veya tüketici mahkemesine başvurabilir. Ticari müşteriler bakımından kanunen yetkili mahkeme ve icra daireleri yetkilidir."),
        ),
    },
    {
        "slug": "on-bilgilendirme-formu",
        "title": "Ön Bilgilendirme Formu",
        "category": "sales",
        "summary": "Ödeme öncesinde hizmet, bedel, ifa ve cayma koşullarına ilişkin zorunlu bilgiler.",
        "requires_acceptance": True,
        "content": _sections(
            ("1. Sağlayıcı", COMMON_PARTIES),
            ("2. Hizmetin temel nitelikleri", "Satın alınan planın adı, kullanım süresi, hesap ve özellik limitleri, AI kredisi veya ürün araştırma adedi sipariş özetinde gösterilir. Güncel özellikler seçilen paket kartı ve ödeme özetiyle birlikte değerlendirilir."),
            ("3. Toplam bedel", "Vergiler dahil toplam tutar, varsa kampanya indirimi ve ödeme yöntemi sipariş onayından hemen önce gösterilir. Sipariş düğmesi işlemin ödeme yükümlülüğü doğurduğunu açıkça belirtir."),
            ("4. İfa ve erişim", "Kart ödemesinde doğrulamanın ardından, havale/EFT yönteminde manuel ödeme onayından sonra hizmet hesabınıza tanımlanır. Dijital hizmet internet bağlantısı ve desteklenen üçüncü taraf platform hesapları gerektirebilir."),
            ("5. Cayma ve istisnalar", "Tüketici hizmet sözleşmesinin kurulduğu tarihten itibaren on dört gün içinde [[SUPPORT_EMAIL]] üzerinden cayma bildiriminde bulunabilir. Tüketicinin önceden açık talebi ve kaybı kabulüyle cayma süresi dolmadan ifasına başlanan veya tamamen ifa edilen hizmetler ile anında teslim edilen dijital haklarda yasal istisnalar uygulanabilir."),
            ("6. Şikayet ve başvuru", "Destek talepleri [[SUPPORT_EMAIL]] adresine iletilir. Tüketici, Ticaret Bakanlığınca ilan edilen parasal sınırlar uyarınca yerleşim yerindeki veya işlemin yapıldığı yerdeki tüketici hakem heyetine ya da tüketici mahkemesine başvurabilir."),
            ("7. Teyit", "Alıcı bu formun ödeme öncesinde okunabilir biçimde sunulduğunu, hizmetin temel niteliklerini ve toplam bedeli gördüğünü elektronik onayla teyit eder. Formun bir kopyası hesap veya e-posta üzerinden kalıcı veri saklayıcısıyla sağlanabilir."),
        ),
    },
    {
        "slug": "uyelik-sozlesmesi",
        "title": "Üyelik Sözleşmesi",
        "category": "sales",
        "summary": "Hesap açılması, kullanıcı yetkileri ve üyeliğin sona ermesine ilişkin kurallar.",
        "requires_acceptance": True,
        "content": _sections(
            ("1. Taraflar ve kabul", COMMON_PARTIES + " Üye, hesap açan gerçek kişi veya temsil ettiği tüzel kişidir. Üye, temsil yetkisine sahip olduğunu kabul eder."),
            ("2. Hesap güvenliği", "Üye doğru ve güncel bilgi verir; parolasını, çok faktörlü doğrulama araçlarını ve bağlı platform erişimlerini korur. Yetkisiz kullanım şüphesini gecikmeden [[SUPPORT_EMAIL]] adresine bildirir."),
            ("3. Kullanım yetkisi", "Üyelik, hizmeti seçilen plan ve belgelerde belirtilen sınırlar içinde kullanmaya yönelik devredilemez ve münhasır olmayan bir hak sağlar. Hesap paylaşımı, erişim sınırlarını aşma, tersine mühendislik, güvenlik önlemlerini aşma ve hukuka aykırı veri kullanımı yasaktır."),
            ("4. Üye içeriği ve bağlantılar", "Üye, bağladığı reklam hesapları ve yüklediği içerikler için gerekli yetkiye sahip olmalıdır. Üçüncü taraf platform izinleri OAuth ekranında verilir ve ilgili platformdan veya ReklamAnaliz.net bağlantı ekranından geri alınabilir."),
            ("5. Ücretli üyelik", "Ücretsiz deneme ücretli abonelik değildir. Ücretli paket ancak kullanıcının açık sipariş ve ödeme onayıyla başlar. Yenileme, iptal ve bedel bilgileri sipariş sırasında gösterilen koşullara tabidir."),
            ("6. Askıya alma ve sona erme", "Güvenlik riski, ödeme ihlali veya ağır kullanım ihlalinde erişim ölçülü biçimde askıya alınabilir. Üye hesabını hesap ayarlarından silme talebi verebilir. Yasal saklama yükümlülükleri ve uyuşmazlık kayıtları saklıdır."),
            ("7. Fikri haklar", "Yazılım, arayüz, marka, model, rapor şablonu ve sağlayıcı tarafından üretilen genel sistem bileşenlerinin hakları sağlayıcıya veya lisans verenlerine aittir. Üyenin kendi veri ve içeriklerindeki hakları üyede kalır."),
            ("8. Değişiklikler", "Esaslı değişiklikler yürürlüğe girmeden önce uygun kanaldan bildirilir. Emredici mevzuatın onay gerektirdiği hallerde yeniden onay alınır; üyenin değişiklik nedeniyle fesih hakkı saklıdır."),
        ),
    },
    {
        "slug": "kvkk-aydinlatma-metni",
        "title": "KVKK Aydınlatma Metni",
        "category": "privacy",
        "summary": "6698 sayılı Kanun kapsamında kişisel veri işleme faaliyetlerine ilişkin aydınlatma.",
        "requires_acceptance": False,
        "content": _sections(
            ("1. Veri sorumlusu", "6698 sayılı Kişisel Verilerin Korunması Kanunu kapsamında veri sorumlusu [[COMPANY_NAME]]'dir. İletişim: [[ADDRESS]], [[KVKK_EMAIL]]."),
            ("2. İşlenen veri kategorileri", "Kimlik ve iletişim bilgileri; üyelik ve yetkilendirme kayıtları; fatura ve işlem bilgileri; bağlı reklam platformlarından kullanıcının izin verdiği hesap, kampanya, reklam, performans ve organik içerik verileri; cihaz, IP, oturum ve güvenlik kayıtları; destek yazışmaları; tercih ve onay kayıtları işlenebilir. Kartın tam numarası ve güvenlik kodu hizmet sağlayıcının kalıcı sistemlerinde saklanmaz."),
            ("3. Amaçlar", "Üyeliğin kurulması, kimlik doğrulama, hizmetin sağlanması, reklam performans raporları ve kullanıcı talebiyle AI analizleri üretilmesi, faturalama, destek, bilgi güvenliği, suistimal önleme, yasal yükümlülüklerin yerine getirilmesi ve hakların tesisi, kullanılması veya korunması amaçlarıyla veri işlenir."),
            ("4. Hukuki sebepler", "Veriler; sözleşmenin kurulması veya ifası için gerekli olma, veri sorumlusunun hukuki yükümlülüğü, bir hakkın tesisi/kullanılması/korunması, temel haklara zarar vermemek kaydıyla meşru menfaat ve kanunlarda açıkça öngörülme şartlarına dayanılarak işlenir. Pazarlama, zorunlu olmayan çerezler veya kanunun ayrıca rıza aradığı faaliyetler yalnızca ayrı açık rıza varsa yürütülür."),
            ("5. Toplama yöntemi", "Veriler web ve mobil arayüzler, üyelik ve ödeme formları, destek kanalları, çerez ve günlük kayıtları, OAuth yetkilendirmesiyle bağlanan platform API'leri ve kullanıcının yüklediği dosyalar üzerinden otomatik veya kısmen otomatik yöntemlerle elde edilir."),
            ("6. Aktarım", "Veriler amaçla sınırlı olarak barındırma, e-posta, hata izleme, ödeme/fatura, destek ve AI hizmeti sunan tedarikçilere; kullanıcının bağladığı Meta, Google, TikTok ve LinkedIn gibi platformlara; yetkili kamu kurumlarına ve hukuken yetkili kişilere aktarılabilir. Yurt dışı aktarım gerektiğinde KVKK'nın güncel 9 uncu maddesindeki yeterlilik, uygun güvence veya arızi aktarım mekanizmalarından uygulanabilir olanı kullanılır."),
            ("7. İlgili kişi hakları", "KVKK'nın 11 inci maddesi kapsamındaki bilgi talep etme, düzeltme, silme veya yok etme isteme, aktarılan üçüncü kişilere bildirim isteme, otomatik analiz sonucuna itiraz ve zararın giderilmesini talep hakları [[KVKK_EMAIL]] adresine kimliği doğrulanabilir bir başvuruyla kullanılabilir. Başvurular kanuni süre içinde yanıtlanır."),
        ),
    },
    {
        "slug": "acik-riza-metni",
        "title": "Açık Rıza Metni",
        "category": "privacy",
        "summary": "Sözleşme için zorunlu olmayan kişisel veri işleme faaliyetlerine yönelik ayrı ve geri alınabilir onay.",
        "requires_acceptance": True,
        "content": _sections(
            ("1. Rızanın kapsamı", "Bu açık rıza, üyelik ve hizmet ifası için zorunlu veri işlemlerinden ayrıdır. Kullanıcı yalnızca arayüzde ayrı ayrı seçtiği pazarlama iletişimi, zorunlu olmayan analitik çerezler veya kişiselleştirme faaliyetlerine rıza verir."),
            ("2. İsteğe bağlılık", "Rıza vermemek temel üyelik ve satın alma hizmetlerinin sunulmasını engellemez. Her amaç için ayrı seçim sunulur; sessizlik, önceden işaretlenmiş kutu veya hizmetin zorunlu şartı açık rıza sayılmaz."),
            ("3. İşleme ve aktarım", "Seçilen amaca göre iletişim bilgisi, kullanım tercihleri ve etkileşim bilgileri kampanya ölçümü, ürün iletişimi veya kişiselleştirme için işlenebilir ve yalnızca bu amaç için hizmet veren tedarikçilere aktarılabilir. Güncel alıcı grupları KVKK Aydınlatma Metninde açıklanır."),
            ("4. Geri alma", "Açık rıza hesap tercihleri, e-posta abonelikten çıkma bağlantısı veya [[KVKK_EMAIL]] üzerinden her zaman geri alınabilir. Geri alma ileriye etkili olup öncesindeki hukuka uygun işlemenin geçerliliğini etkilemez."),
            ("5. Kayıt", "Rızanın zamanı, kapsamı, kullanılan metnin sürümü ve geri alma işlemi ispat ve uyum amacıyla güvenli şekilde kaydedilebilir."),
        ),
    },
    {
        "slug": "gizlilik-politikasi",
        "title": "Gizlilik Politikası",
        "category": "privacy",
        "summary": "Kullanıcı ve reklam verilerinin nasıl toplandığı, kullanıldığı, korunduğu ve paylaşıldığı.",
        "content": _sections(
            ("1. Yaklaşımımız", "[[BRAND_NAME]], kişisel ve ticari reklam verilerini belirli, açık ve meşru amaçlarla; gerekli olanla sınırlı ve güvenli biçimde işler. Kullanıcı verileri satılmaz ve izinsiz reklam hedefleme profili oluşturmak için üçüncü kişilere sunulmaz."),
            ("2. Toplanan bilgiler", "Hesap ve iletişim bilgileri, abonelik ve fatura verileri, kullanım ve güvenlik günlükleri, destek kayıtları ile kullanıcının OAuth aracılığıyla bağladığı reklam hesabı ve performans verileri toplanabilir."),
            ("3. Kullanım", "Veriler paneli çalıştırmak, rapor ve uyarı üretmek, kullanıcının seçtiği AI analizini gerçekleştirmek, hizmet kalitesi ve güvenliğini korumak, destek vermek ve yasal yükümlülükleri yerine getirmek için kullanılır."),
            ("4. Paylaşım", "Paylaşım; hizmeti çalıştıran sözleşmeli altyapı sağlayıcıları, ödeme/fatura kuruluşları, kullanıcının bağladığı platformlar ve yasal olarak yetkili kurumlarla amaç ve yetki sınırında yapılır. Tedarikçilere gizlilik ve güvenlik yükümlülükleri uygulanır."),
            ("5. Kontrolünüz", "Bağlı platform erişimi kaldırılabilir; hesap bilgileri düzeltilebilir; pazarlama tercihleri değiştirilebilir; erişim, dışa aktarma ve silme talepleri [[KVKK_EMAIL]] adresine iletilebilir."),
            ("6. Güvenlik ve saklama", "Erişim kontrolü, şifreleme, günlükleme, yedekleme ve olay müdahale önlemleri uygulanır. Veriler yalnızca amaç ve yasal yükümlülük için gerekli süre boyunca saklanır; ayrıntılar Veri Saklama ve Veri Silme politikalarındadır."),
            ("7. İletişim", "Gizlilik soruları ve başvurular için: [[COMPANY_NAME]], [[ADDRESS]], [[KVKK_EMAIL]]."),
        ),
    },
    {
        "slug": "cerez-politikasi",
        "title": "Çerez Politikası",
        "category": "privacy",
        "summary": "Zorunlu ve isteğe bağlı çerezlerin amaçları ile tercih yönetimi.",
        "content": _sections(
            ("1. Çerez nedir?", "Çerezler, siteyi ziyaret ettiğinizde tarayıcınıza kaydedilen küçük metin dosyalarıdır. Benzer yerel depolama teknolojileri de bu politika kapsamında değerlendirilir."),
            ("2. Zorunlu çerezler", "Oturum açma, güvenlik, CSRF koruması, dil ve temel arayüz tercihlerinin çalışması için gerekli çerezler sözleşmenin ifası ve güvenlik amacıyla kullanılır. Bunlar devre dışı bırakıldığında hizmetin bazı bölümleri çalışmayabilir."),
            ("3. Analitik ve pazarlama çerezleri", "Zorunlu olmayan ölçüm, kişiselleştirme veya pazarlama çerezleri ancak önceden bilgilendirme ve geçerli tercih sonrasında çalıştırılır. Rıza gerektiren çerezler, kullanıcı kabul etmeden yerleştirilmez."),
            ("4. Tercihlerin yönetimi", "Kullanıcı çerez panelinden tercihini kategori bazında verebilir veya geri alabilir. Tarayıcı ayarlarından çerezler silinebilir; rızanın geri alınması önceki hukuka uygun işlemleri etkilemez."),
            ("5. Süreler ve üçüncü taraflar", "Oturum çerezleri tarayıcı oturumu sonunda; kalıcı çerezler çerez panelinde belirtilen sürede sona erer. Üçüncü taraf çerezlerinin sağlayıcısı, amacı ve süresi tercih panelinde güncel olarak gösterilir."),
            ("6. İletişim", "Çerezlerle ilgili talepler [[KVKK_EMAIL]] adresine iletilebilir."),
        ),
    },
    {
        "slug": "kullanim-kosullari",
        "title": "Kullanım Koşulları",
        "category": "sales",
        "summary": "Web sitesi, panel, raporlar ve entegrasyonların kabul edilebilir kullanım kuralları.",
        "requires_acceptance": True,
        "content": _sections(
            ("1. Kapsam", "Bu koşullar [[BRAND_NAME]] web sitesi, paneli, API bağlantıları, raporları ve AI özelliklerinin kullanımını düzenler. Ücretli alımlarda Mesafeli Satış Sözleşmesi ve Ön Bilgilendirme Formu ayrıca uygulanır."),
            ("2. İzin verilen kullanım", "Hizmet yalnızca kullanıcının yetkili olduğu reklam hesapları ve hukuka uygun ticari amaçlar için kullanılabilir. Platform koşullarına, fikri mülkiyet ve kişisel veri mevzuatına uyulmalıdır."),
            ("3. Yasaklar", "Yetkisiz erişim, kimlik taklidi, zararlı yazılım, oran sınırı aşma, veri kazıma, güvenlik testi için izinsiz saldırı, hizmeti yeniden satma, üçüncü kişi verilerini izinsiz profilleme ve hukuka aykırı reklam üretimi yasaktır."),
            ("4. Analizlerin niteliği", "Raporlar ve AI önerileri karar destek amaçlıdır; kesin sonuç, gelir veya reklam performansı garantisi değildir. Reklam yayını ve bütçe kararının nihai kontrolü kullanıcıdadır."),
            ("5. Erişilebilirlik ve değişiklik", "Bakım, güvenlik olayı veya üçüncü taraf platform kesintileri nedeniyle erişim geçici olarak sınırlanabilir. Esaslı koşul değişiklikleri uygun süre önce bildirilir."),
            ("6. İhlal", "İhlalin niteliğine göre uyarı, özellik kısıtlaması, geçici askı veya sözleşmenin feshi uygulanabilir. Acil güvenlik ve hukuka aykırılık hallerinde önceden bildirim yapılmadan tedbir alınabilir."),
        ),
    },
    {
        "slug": "iptal-ve-iade-politikasi",
        "title": "İptal ve İade Politikası",
        "category": "sales",
        "summary": "Ücretsiz deneme, abonelik iptali, cayma ve bedel iadesi esasları.",
        "content": _sections(
            ("1. Ücretsiz deneme", "[[BRAND_NAME]] başlangıçta on dört günlük ücretsiz kullanım sunabilir. Ücretsiz dönem bir para iade garantisi değildir. Kullanıcı açıkça ücretli sipariş vermedikçe deneme nedeniyle ücret tahsil edilmez."),
            ("2. Abonelik iptali", "Abonelik, hesap veya destek kanalı üzerinden iptal edilebilir. İptal, aksi sipariş koşulunda belirtilmedikçe mevcut ödenmiş dönemin sonunda yenilemeyi durdurur. Kullanıcı iptal teyidini saklamalıdır."),
            ("3. Tüketicinin cayma hakkı", "Tüketici, mesafeli hizmet sözleşmesinin kurulmasından itibaren on dört gün içinde yazılı veya kalıcı veri saklayıcısıyla cayma bildiriminde bulunabilir. Cayma süresi dolmadan hizmetin başlaması ayrıca açık talep ve mevzuatın gerektirdiği bilgilendirmeye tabidir."),
            ("4. Dijital hizmet istisnaları", "Tüketicinin açık talebi ve onayıyla tamamen ifa edilen hizmetlerde veya anında teslim edilerek kullanılan dijital kredi/haklarda cayma hakkı mevzuattaki ölçüde sona erebilir. Emredici tüketici hakları her durumda saklıdır."),
            ("5. İade yöntemi", "İade hakkı doğduğunda bedel yasal süre içinde, tüketiciye masraf yüklemeksizin ve kural olarak ilk ödeme aracına uygun biçimde yapılır. Banka ve ödeme kuruluşunun hesaba yansıtma süreleri değişebilir."),
            ("6. Hatalı veya mükerrer tahsilat", "Mükerrer işlem, yanlış tutar veya hizmetin sağlayıcı kaynaklı hiç sunulamaması halinde [[SUPPORT_EMAIL]] adresine ödeme belgesiyle başvurulabilir. İnceleme sonucunda düzeltme veya iade yapılır."),
        ),
    },
    {
        "slug": "veri-silme-politikasi",
        "title": "Veri Silme Politikası",
        "category": "privacy",
        "summary": "Hesap, bağlı platform ve kişisel veriler için silme talebi ve imha süreci.",
        "content": _sections(
            ("1. Talep kanalları", "Kullanıcı hesap silme özelliğinden veya [[KVKK_EMAIL]] adresinden silme talebi iletebilir. Güvenlik için hesap sahipliği ve kimlik doğrulanabilir; gereğinden fazla kimlik belgesi istenmez."),
            ("2. Bağlantının kaldırılması", "Meta, Google, TikTok veya LinkedIn bağlantısı kaldırıldığında yeni veri çekimi durdurulur ve erişim belirteci kullanılamaz hale getirilir. Kullanıcı ilgili platformun güvenlik ayarlarından da uygulama erişimini iptal edebilir."),
            ("3. Silme kapsamı", "Aktif işleme amacı ve hukuki saklama zorunluluğu kalmayan hesap, profil, platform verisi, rapor, içerik ve erişim belirteçleri silinir, yok edilir veya anonim hale getirilir. Yasal fatura, işlem, güvenlik ve uyuşmazlık kayıtları süre sonuna kadar kısıtlı erişimle tutulabilir."),
            ("4. Süreç ve yedekler", "Talep kanuni süre içinde yanıtlanır. Aktif sistemlerden silinen kayıtlar, yedekleme döngüsü tamamlanana kadar erişime kapalı biçimde sınırlı süre kalabilir ve geri yükleme halinde yeniden silme kuyruğuna alınır."),
            ("5. Üçüncü taraflar", "Silme yükümlülüğü doğduğunda verinin aktarıldığı hizmet sağlayıcılara gerekli bildirim yapılır. Üçüncü taraf platformun kendi hesabında tuttuğu veriler için ilgili platformun silme araçları kullanılır."),
            ("6. Sonuç bildirimi", "Tamamlanan işlem, reddedilen bölüm ve hukuki gerekçesi başvuru sahibine bildirilir. Başvuru sahibi KVKK kapsamındaki şikayet ve başvuru haklarını kullanabilir."),
        ),
    },
    {
        "slug": "veri-saklama-politikasi",
        "title": "Veri Saklama Politikası",
        "category": "privacy",
        "summary": "Veri kategorileri için saklama ölçütleri, süreler ve periyodik imha yaklaşımı.",
        "content": _sections(
            ("1. İlkeler", "Veriler belirli işleme amacı, sözleşme süresi, kanuni zamanaşımı ve yasal yükümlülükler dikkate alınarak gerekli olan en kısa süre boyunca saklanır. Süresi dolan veri silinir, yok edilir veya anonim hale getirilir."),
            ("2. Temel süreler", "Hesap ve abonelik verileri ilişki boyunca ve uyuşmazlık zamanaşımı süresince; fatura ve ticari kayıtlar ilgili vergi ve ticaret mevzuatındaki süre boyunca; güvenlik günlükleri riskle orantılı ve kural olarak iki yılı aşmayacak şekilde; destek kayıtları talebin kapanması ve makul uyuşmazlık süresince saklanır."),
            ("3. Platform ve reklam verileri", "Bağlı reklam hesabı verileri bağlantı ve raporlama amacı sürdüğü müddetçe tutulur. Bağlantı kaldırıldığında aktif kopyalar silme kuyruğuna alınır; hukuki zorunluluk yoksa platform verileri ve erişim belirteçleri amaç sona erdikten sonra tutulmaz."),
            ("4. Pazarlama ve rıza", "Pazarlama tercihleri rıza geri alınana veya işleme amacı sona erene kadar; rıza ve ret kayıtları ise hukuki ispat için gerekli süre boyunca sınırlı erişimle saklanabilir."),
            ("5. Yedek ve anonim veri", "Yedekler sınırlı erişim ve döngüsel silme esasına tabidir. Geri döndürülemeyecek biçimde anonim hale getirilen istatistikler kişisel veri niteliğini kaybettikten sonra ürün güvenliği ve kapasite planlama için saklanabilir."),
            ("6. Periyodik gözden geçirme", "Saklama süreleri en az yılda bir ve mevzuat veya platform politikası değiştiğinde gözden geçirilir. İmha işlemleri kayıt altına alınır."),
        ),
    },
    {
        "slug": "guvenlik-politikasi",
        "title": "Güvenlik Politikası",
        "category": "service",
        "summary": "Hesap, altyapı, erişim belirteci ve olay yönetimi güvenlik ilkeleri.",
        "content": _sections(
            ("1. Güvenlik yönetimi", "[[BRAND_NAME]], risk temelli teknik ve idari tedbirler uygular. Yetkiler görev ve ihtiyaçla sınırlanır; kritik işlemler günlüklenir ve periyodik olarak gözden geçirilir."),
            ("2. Kimlik ve erişim", "Güçlü parola, uygun yerlerde çok faktörlü doğrulama, oturum süresi, oran sınırlama ve yetki ayrımı kullanılır. Kullanıcılar kimlik bilgilerini paylaşmamalı ve şüpheli erişimi bildirmelidir."),
            ("3. Veri ve sırlar", "Aktarım sırasında TLS, uygun alanlarda depolama şifrelemesi ve erişim belirteçleri için uygulama seviyesinde koruma uygulanır. API anahtarları istemci tarafı koduna veya herkese açık depolara konulmaz."),
            ("4. Uygulama ve altyapı", "Güvenlik güncellemeleri, bağımlılık takibi, yedekleme, hata izleme, erişim günlükleri ve kötüye kullanım kontrolleri uygulanır. Üretim ve geliştirme ortamları mümkün olan ölçüde ayrılır."),
            ("5. Olay müdahalesi", "Şüpheli olaylar sınıflandırılır, sınırlandırılır, deliller korunur, kök neden giderilir ve tekrarını önleyici işlem alınır. İlgili kişilere ve yetkili kurumlara mevzuatın gerektirdiği kapsam ve sürede bildirim yapılır."),
            ("6. Güvenlik bildirimi", "Güvenlik açığı bildirimleri ayrıntı ve tekrar adımlarıyla [[SUPPORT_EMAIL]] adresine iletilebilir. İyi niyetli bildirimlerde veriye zarar verilmemesi, erişimin genişletilmemesi ve bulgunun kamuya açıklanmadan önce çözüm süresi tanınması beklenir."),
        ),
    },
    {
        "slug": "yapay-zeka-kullanim-politikasi",
        "title": "Yapay Zeka Kullanım Politikası",
        "category": "ai",
        "summary": "AI destekli analizlerin veri kullanımı, sınırları ve kullanıcı sorumlulukları.",
        "content": _sections(
            ("1. Kapsam", "AI özellikleri reklam performansı özeti, öneri, metin taslağı, anomali açıklaması ve karar desteği sağlayabilir. Kullanılan model ve sağlayıcı, özellik ve kapasiteye göre değişebilir."),
            ("2. Veri minimizasyonu", "Modele yalnızca istenen çıktıyı üretmek için gerekli veri gönderilir. Parola, tam ödeme kartı bilgisi, özel nitelikli kişisel veri veya gereksiz doğrudan tanımlayıcıların istemlere eklenmemesi esastır."),
            ("3. İnsan kontrolü", "AI çıktıları olasılıksal olabilir; hatalı, eksik veya güncelliğini yitirmiş sonuç üretebilir. Bütçe, yayın, hedefleme ve hukuki etki doğuran kararlar kullanıcı incelemesi ve açık komutu olmadan kesin işlem sayılmaz."),
            ("4. Yasak kullanım", "Ayrımcılık, yanıltıcı reklam, izinsiz kişisel profilleme, hassas özellik çıkarımı, fikri hak ihlali, zararlı içerik veya platform kurallarını aşma amacıyla AI kullanılamaz."),
            ("5. Tedarikçiler", "Harici AI sağlayıcısı kullanıldığında veri işleme ve güvenlik koşulları değerlendirilir; aktarım amaç ve sözleşmeyle sınırlandırılır. Kullanıcı verilerinin model eğitimi için kullanımı ancak açıklanan hukuki temel ve gerekli tercih mekanizmasıyla mümkündür."),
            ("6. Geri bildirim", "Kullanıcı hatalı veya sakıncalı çıktıyı [[SUPPORT_EMAIL]] adresine bildirebilir. Yüksek etkili özellikler düzenli risk değerlendirmesine tabi tutulur."),
        ),
    },
    {
        "slug": "reklam-verisi-kullanim-politikasi",
        "title": "Reklam Verisi Kullanım Politikası",
        "category": "platform",
        "summary": "Bağlı reklam hesaplarından alınan kampanya ve performans verilerinin kullanım kuralları.",
        "content": _sections(
            ("1. Veri kaynağı", "Reklam verileri kullanıcının yetkilendirdiği resmi API bağlantıları, kullanıcı yüklemeleri ve izin verilen herkese açık reklam kaynaklarından elde edilir. Yetkisiz kimlik bilgisi veya belgelenmemiş API kullanılmaz."),
            ("2. Veri türleri", "Hesap ve kampanya kimlikleri, reklam grubu ve kreatif bilgileri, bütçe, harcama, gösterim, tıklama, dönüşüm, gelir/ROAS, erişim, sıklık ve platformun izin verdiği toplulaştırılmış kitle metrikleri işlenebilir."),
            ("3. Amaç", "Veri panelde gösterim, karşılaştırma, raporlama, anomali tespiti, bütçe optimizasyonu ve kullanıcının talep ettiği AI karar desteği için kullanılır. Kullanıcının bağlı hesabı dışındaki kişilere özel reklam verisi açıklanmaz."),
            ("4. Yasak işlemler", "Platform verisi satılmaz; izinsiz gözetim, hassas özellik çıkarımı, ayrımcı hedefleme, platform limitlerini aşma, yeniden kimliklendirme veya başka müşterinin hesabıyla birleştirme için kullanılmaz."),
            ("5. Paylaşım ve saklama", "Paylaşım yalnızca hizmeti sunan yetkili alt işleyenlerle ve gerekli kapsamda yapılır. Bağlantı sona erdiğinde yeni çekim durur ve veri, saklama/silme politikaları ile platformun daha kısa süre öngören kuralına göre kaldırılır."),
            ("6. Kullanıcı sorumluluğu", "Kullanıcı bağladığı hesapta gerekli yönetim yetkisine ve ilgili kişilere yönelik geçerli hukuki temele sahip olmalıdır. Raporların üçüncü kişilerle paylaşımında gizlilik ve platform koşulları korunmalıdır."),
        ),
    },
    {
        "slug": "meta-platform-veri-kullanim-bildirimi",
        "title": "Meta Platform Veri Kullanım Bildirimi",
        "category": "platform",
        "summary": "Facebook ve Instagram bağlantılarından alınan verilerin kullanımı ve silinmesi.",
        "content": _sections(
            ("1. Yetkilendirme", "Meta bağlantısı OAuth ve Meta'nın sunduğu resmi Graph/Marketing API araçlarıyla kurulur. İzin ekranında gösterilen kapsamlar, hesap ve reklam verilerini okuma; kullanıcı ayrıca etkinleştirmişse yönetim veya içerik yayınlama işlevleri için istenir."),
            ("2. Alınan veriler", "Yetkili işletme, sayfa ve Instagram hesap kimlikleri; kampanya, reklam seti, reklam, kreatif, performans içgörüleri ve izin verilen organik içerik metrikleri alınabilir. Kullanıcının vermediği izin kapsamındaki veriye erişilmez."),
            ("3. Kullanım", "Veri yalnızca bağlı hesabın panelde gösterimi, raporlanması, kullanıcı talimatıyla analiz edilmesi ve izin verilen yönetim/yayın işlemleri için kullanılır. Meta verisi satılmaz veya bağımsız reklam profili oluşturmak üzere paylaşılmaz."),
            ("4. Güvenlik", "Erişim belirteçleri şifreli veya eşdeğer korumalı biçimde, en az yetki ve sınırlı erişimle saklanır. Süresi dolan veya iptal edilen belirteçlerle erişim yapılmaz."),
            ("5. Bağlantıyı kaldırma ve silme", "Kullanıcı ReklamAnaliz.net bağlantı ekranından veya Meta Business Integrations ayarlarından erişimi kaldırabilir. Kaldırma sonrası yeni veri çekimi durur; silme talebi [[KVKK_EMAIL]] adresine iletilebilir ve yasal olarak tutulması gerekmeyen Meta verileri silinir."),
            ("6. Meta kuralları", "Kullanım, yürürlükteki Meta Platform Terms, Developer Policies ve ilgili ürün koşullarına tabidir. Meta'nın izin veya saklama kuralı bu bildirimden daha sıkıysa daha sıkı kural uygulanır."),
        ),
    },
    {
        "slug": "google-ads-veri-kullanim-bildirimi",
        "title": "Google Ads Veri Kullanım Bildirimi",
        "category": "platform",
        "summary": "Google Ads ve Google API kullanıcı verilerinin erişim, kullanım, paylaşım ve silme esasları.",
        "content": _sections(
            ("1. OAuth erişimi", "Google bağlantısı resmi OAuth 2.0 akışıyla ve yalnızca özelliğin gerektirdiği kapsamlarla kurulur. İzin ekranı uygulamanın kimliğini, talep edilen veriyi ve amacı gösterir."),
            ("2. Veri kapsamı", "Yetkilendirilen Google Ads müşteri ve kampanya bilgileri, reklam grupları, reklamlar, anahtar kelime ve performans metrikleri; ayrıca kullanıcı bağlarsa salt okunur Analytics raporları alınabilir."),
            ("3. Sınırlı kullanım", "Google kullanıcı verileri yalnızca kullanıcıya görünen reklam analizi, raporlama, senkronizasyon ve talep edilen özellikleri sağlamak için kullanılır. Veriler satılmaz, ilgisiz reklamcılık amacıyla aktarılmaz ve insan tarafından okunması yalnızca güvenlik, destek, hukuk veya kullanıcının açık izni gereken sınırlı hallerde gerçekleşir."),
            ("4. Paylaşım", "Aktarım yalnızca özelliği sağlayan sözleşmeli altyapı işleyenlerine, kullanıcının açık talimat verdiği kişilere veya hukuki zorunluluk halinde yetkili kurumlara yapılır. Google API verisi genel amaçlı model eğitimi için kullanılmaz."),
            ("5. Güvenlik ve saklama", "Erişim belirteçleri korumalı tutulur, istemci sırları açığa çıkarılmaz ve gerekli olmayan kapsamlar istenmez. Veri yalnızca kullanıcıya sunulan işlev için gerekli süre boyunca tutulur."),
            ("6. Erişimi kaldırma", "Kullanıcı bağlantıyı ReklamAnaliz.net'ten veya Google Hesabı üçüncü taraf erişim sayfasından iptal edebilir. Silme talebi [[KVKK_EMAIL]] adresine iletilebilir."),
            ("7. Google politikaları", "Kullanım Google APIs Terms of Service, Google API Services User Data Policy, OAuth 2.0 Policies ve ilgili Google Ads koşullarına tabidir. Daha sıkı Google kuralı öncelikle uygulanır."),
        ),
    },
    {
        "slug": "tiktok-api-veri-kullanim-bildirimi",
        "title": "TikTok API Veri Kullanım Bildirimi",
        "category": "platform",
        "summary": "TikTok for Business/API bağlantısıyla erişilen verilerin kullanım ve silme esasları.",
        "content": _sections(
            ("1. Bağlantı", "TikTok verisine yalnızca resmi OAuth ve onaylı TikTok API ürünleri üzerinden, kullanıcının seçtiği hesaplar ve verdiği izinler kapsamında erişilir."),
            ("2. Veri türleri", "Yetkili reklamveren ve hesap kimlikleri, kampanya/reklam grubu/reklam bilgileri, kreatif meta verileri, bütçe ve toplulaştırılmış performans metrikleri işlenebilir. İzin verilmeyen profil veya içerik verisi çekilmez."),
            ("3. Amaç ve sınırlar", "Veri panel, rapor, senkronizasyon ve kullanıcı talimatlı analiz için kullanılır. TikTok verisi satılmaz; gözetim, hassas profil çıkarımı, ayrımcı hedefleme veya TikTok kısıtlarını aşmak amacıyla kullanılmaz."),
            ("4. Saklama ve güvenlik", "Belirteçler korumalı tutulur; veri erişimi görevle sınırlanır. TikTok'un belirlediği yenileme, saklama ve silme süreleri uygulanır; işlev sona erdiğinde gereksiz kopyalar kaldırılır."),
            ("5. İptal ve silme", "Kullanıcı TikTok yetkilendirme ayarlarından veya ReklamAnaliz.net bağlantı ekranından erişimi kaldırabilir. Kaldırma yeni veri çekimini durdurur. Silme talepleri [[KVKK_EMAIL]] adresine iletilebilir."),
            ("6. Geçerli kurallar", "TikTok for Developers ve TikTok for Business sözleşmeleri, veri koruma koşulları ve ürün politikaları güncel halleriyle uygulanır; daha sıkı platform kuralı önceliklidir."),
        ),
    },
    {
        "slug": "linkedin-api-veri-kullanim-bildirimi",
        "title": "LinkedIn API Veri Kullanım Bildirimi",
        "category": "platform",
        "summary": "LinkedIn Marketing API verilerinin yetkili erişim, kullanım, saklama ve silme esasları.",
        "content": _sections(
            ("1. Yetkili erişim", "LinkedIn erişimi OAuth 2.0 ve yalnızca LinkedIn'in uygulamaya onayladığı ürün/izinler üzerinden sağlanır. Kullanıcının yönetmeye yetkili olmadığı sayfa, profil veya reklam hesabına erişilmez."),
            ("2. Veri kapsamı", "Yetkilendirilen kuruluş, reklam hesabı, kampanya, kreatif ve toplulaştırılmış performans verileri; onaylanan izinlerin kapsamına göre alınabilir. Üye verileri yalnızca açıkça izin verilen özellik için işlenir."),
            ("3. Kullanım sınırlaması", "LinkedIn verisi bağlı sayfa veya reklam faaliyetlerini yönetme, analiz etme ve raporlama amacıyla kullanılır. Üye verisi satılmaz, izinsiz zenginleştirme veya yeniden kimliklendirme yapılmaz ve izin verilen kullanım dışına çıkarılmaz."),
            ("4. Saklama", "LinkedIn Marketing API Program Data Storage Requirements dahil geçerli saklama süreleri izlenir. Platformun daha kısa bir süre belirlediği veri güncellenir veya silinir; gereksiz kalıcı kopya oluşturulmaz."),
            ("5. İptal ve silme", "Kullanıcı LinkedIn ayarlarından veya ReklamAnaliz.net bağlantı ekranından yetkiyi kaldırabilir. Talep üzerine ve platform kuralı gerektirdiğinde veriler silinir; talepler [[KVKK_EMAIL]] adresinden alınır."),
            ("6. Geçerli kurallar", "LinkedIn API Terms, Marketing API Platform Terms, veri saklama gereklilikleri ve ilgili geliştirici kuralları uygulanır. Ayrı bir LinkedIn sözleşmesi varsa o sözleşmedeki daha özel hükümler geçerlidir."),
        ),
    },
    {
        "slug": "sla-hizmet-seviyesi-sozlesmesi",
        "title": "SLA (Hizmet Seviyesi Sözleşmesi)",
        "category": "service",
        "summary": "Ücretli hizmet için erişilebilirlik hedefi, bakım, destek ve istisnalar.",
        "content": _sections(
            ("1. Kapsam", "Bu SLA, aksi sipariş formunda kararlaştırılmadıkça aktif ücretli ReklamAnaliz.net abonelikleri için uygulanır. Ücretsiz deneme, beta özellikler ve ücretsiz hizmetler kapsam dışıdır."),
            ("2. Erişilebilirlik hedefi", "Aylık hizmet erişilebilirliği hedefi <strong>%[[SLA_TARGET]]</strong>'dir. Erişilebilirlik, toplam ölçüm süresinden kapsam dışı kesintiler çıkarıldıktan sonra hizmetin temel panel fonksiyonlarına erişilebildiği sürenin oranıdır."),
            ("3. Kapsam dışı durumlar", "Önceden bildirilen planlı bakım; mücbir sebep; internet/telekom kesintisi; kullanıcı sistemi veya yanlış yapılandırması; Meta, Google, TikTok, LinkedIn, ödeme kuruluşu ya da diğer üçüncü taraf API kesintileri; güvenlik tehdidine karşı acil tedbirler hedef hesabına dahil edilmez."),
            ("4. Bakım", "Planlı bakım mümkün olduğunda düşük kullanım saatlerinde yapılır ve makul süre önce duyurulur. Kritik güvenlik bakımında ön bildirim süresi kısalabilir."),
            ("5. Destek", "Kritik erişim sorunları [[SUPPORT_EMAIL]] üzerinden alınır. Öncelik, etkilenen kullanıcı sayısı, veri güvenliği ve temel hizmetin çalışıp çalışmamasına göre belirlenir. Yanıt süresi çözüm garantisi değil, incelemenin başladığı süreyi ifade eder."),
            ("6. Ölçüm ve talep", "Aylık ölçüm sağlayıcının sunucu ve izleme kayıtlarına dayanır. Müşteri, ilgili ayın bitiminden itibaren otuz gün içinde olay zamanları ve hesap bilgisiyle inceleme talep edebilir."),
            ("7. Telafi", "Standart paketlerde özel hizmet kredisi ancak sipariş formunda ayrıca belirtilmişse uygulanır. Tüketicinin emredici hakları ve hizmetin ayıplı ifasına ilişkin yasal başvuruları saklıdır."),
        ),
    },
    {
        "slug": "ai-etik-ilkeleri",
        "title": "AI Etik İlkeleri",
        "category": "ai",
        "summary": "AI özelliklerinin adil, açıklanabilir, güvenli ve insan denetimli geliştirilmesine ilişkin ilkeler.",
        "content": _sections(
            ("1. İnsan odaklılık", "AI, insan kararını desteklemek için kullanılır; kullanıcıların haklarını ortadan kaldıran veya açıklanamaz biçimde yüksek etkili otomatik karar veren bir otorite olarak tasarlanmaz."),
            ("2. Adalet", "Model çıktılarında ayrımcılık ve temsil hatası riski değerlendirilir. Hassas özelliklere dayalı dışlama, manipülasyon veya hukuka aykırı reklam hedeflemesi desteklenmez."),
            ("3. Şeffaflık", "Kullanıcıya AI kullanılan özellik, çıktının öneri niteliği ve temel sınırlamalar anlaşılır biçimde belirtilir. Mümkün olduğunda öneriyi etkileyen metrikler ve gerekçeler gösterilir."),
            ("4. Gizlilik", "Veri minimizasyonu, amaçla sınırlılık ve güvenli aktarım uygulanır. Müşteri reklam verisi, açıklanmış bir hukuki temel ve gerekli kontrol olmadan genel model eğitimi için kullanılmaz."),
            ("5. Güvenlik ve sağlamlık", "Model değişiklikleri, istem güvenliği, hatalı çıktı, kötüye kullanım ve veri sızıntısı riskleri test edilir. Kritik özelliklerde geri alma, kayıt ve insan müdahalesi mekanizmaları korunur."),
            ("6. Hesap verebilirlik", "AI özelliğinin sahibi, kullanım amacı ve risk kontrolleri belirlenir. Olaylar ve ciddi geri bildirimler incelenir; gerektiğinde özellik sınırlandırılır veya durdurulur."),
            ("7. Sürekli iyileştirme", "İlkeler mevzuat, teknik standartlar, model davranışı ve kullanıcı geri bildirimi ışığında düzenli olarak gözden geçirilir."),
        ),
    },
]

