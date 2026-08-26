function showSpeech(text){
  const pill=document.getElementById('octoSpeechPill');
  const span=document.getElementById('octoSpeechText');
  if(span) span.innerText=text;
  if(pill){ pill.classList.add('show'); setTimeout(()=>pill.classList.remove('show'), 7200); }
}
async function octoSpeak(page){
  let text='Octo AI analiz ediyor.';
  try{
    const res=await fetch(`/api/v2/octo/speech/?page=${encodeURIComponent(page||'kontrol')}`,{headers:{'X-Requested-With':'XMLHttpRequest'}});
    const data=await res.json();
    if(data.success) text=data.text;
  }catch(e){ console.warn(e); }
  showSpeech(text);
  if('speechSynthesis' in window){
    window.speechSynthesis.cancel();
    const utter=new SpeechSynthesisUtterance(text);
    utter.lang='tr-TR'; utter.rate=.94; utter.pitch=1.05;
    window.speechSynthesis.speak(utter);
  }
}
function closeV2Phone(){
  const m=document.getElementById('v2PhoneModal');
  if(m){m.classList.remove('show');m.setAttribute('aria-hidden','true');document.body.classList.remove('v2-modal-open');}
}
function openFirstRisk(){
  const first=document.querySelector('.v2-open-phone[data-modal-type="ad"]');
  if(first) first.click();
}
function bindModalTabs(){
  document.querySelectorAll('[data-modal-tab]').forEach(btn=>{
    btn.addEventListener('click',()=>{
      const key=btn.dataset.modalTab;
      btn.closest('.modal-tabs').querySelectorAll('button').forEach(x=>x.classList.remove('active'));
      btn.classList.add('active');
      document.querySelectorAll('.modal-pane').forEach(p=>p.classList.remove('active'));
      const pane=document.getElementById('modal-'+key); if(pane) pane.classList.add('active');
    });
  });
}
document.addEventListener('DOMContentLoaded',()=>{
  const modal=document.getElementById('v2PhoneModal');
  if(modal && modal.parentElement!==document.body) document.body.appendChild(modal);
  const periodBtn=document.getElementById('periodBtn');
  const periodMenu=document.getElementById('periodMenu');
  if(periodBtn && periodMenu){
    periodBtn.addEventListener('click',(e)=>{e.stopPropagation();periodMenu.classList.toggle('show');});
    periodMenu.querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>{document.getElementById('periodLabel').innerText=b.dataset.period;periodMenu.classList.remove('show');showSpeech(`${b.dataset.period} görünümüne geçildi. Ekrandaki gerçek hesaplar bu periyoda göre yorumlanacak.`)}));
    document.addEventListener('click',()=>periodMenu.classList.remove('show'));
  }
  document.querySelectorAll('[data-preview-tab]').forEach(btn=>{
    btn.addEventListener('click',()=>{
      const key=btn.dataset.previewTab;
      btn.parentElement.querySelectorAll('button').forEach(x=>x.classList.remove('active'));
      btn.classList.add('active');
      document.querySelectorAll('.phone-preview-pane').forEach(p=>p.classList.remove('active'));
      const pane=document.getElementById('preview-'+key); if(pane) pane.classList.add('active');
    });
  });
});
document.addEventListener('click',async(e)=>{
  const b=e.target.closest('.v2-open-phone'); if(!b) return;
  const modal=document.getElementById('v2PhoneModal'); const body=document.getElementById('v2PhoneBody'); const title=document.getElementById('v2PhoneTitle');
  if(!modal||!body) return;
  modal.classList.add('show'); modal.setAttribute('aria-hidden','false');document.body.classList.add('v2-modal-open');
  const name=b.querySelector('.compact-main strong,.row-main strong,.v2-ad-card strong,.v2-rival-card strong')?.innerText || 'Detay';
  const sub=b.querySelector('.compact-main small,.row-main span,.v2-ad-card small,.v2-rival-card small')?.innerText || '';
  const score=b.querySelector('.row-score')?.innerText || (b.querySelector('.mini-action')?.innerText||'—');
  const media=b.querySelector('.tiny-media img,.row-media img,.ad-card-top img')?.src || '';
  const isComp=b.dataset.modalType==='competitor';
  if(title) title.innerText=name;
  const tabs = isComp
    ? '<button class="active" data-modal-tab="overview">Gözlem</button><button data-modal-tab="performance">Hareket</button><button data-modal-tab="history">Geçmiş</button>'
    : '<button class="active" data-modal-tab="overview">Genel Bakış</button><button data-modal-tab="performance">Performans</button><button data-modal-tab="advice">Öneriler</button><button data-modal-tab="history">Geçmiş</button>';
  const why = isComp
    ? 'Rakip reklamı üzerinde düzenleme yapılmaz. Bu kayıt sadece rakibin mesajını, kreatif formatını ve kampanya hareketini anlamak için izlenir.'
    : 'Bu reklam düşük skor, düşük CTR, yüksek frekans veya zayıf ROAS nedeniyle aksiyon listesine alındı.';
  body.innerHTML=`
    <div class="v2-phone-hero">
      ${media?`<img src="${media}" alt="${name}">`:`<div class="modal-placeholder"><i class="fa-regular fa-image"></i></div>`}
      <h2>${name}</h2><p class="modal-sub">${sub}</p>
      <div class="modal-tabs">${tabs}</div>
      <div id="modal-overview" class="modal-pane active">
        <div class="v2-phone-grid"><div class="v2-phone-metric"><strong>${score}</strong><span>${isComp?'Tehdit skoru':'Sağlık skoru'}</span></div><div class="v2-phone-metric"><strong>${isComp?'Gözlem':'Aksiyon'}</strong><span>Mod</span></div><div class="v2-phone-metric"><strong>7 Gün</strong><span>Periyot</span></div><div class="v2-phone-metric"><strong>${isComp?'Pasif':'Canlı'}</strong><span>Durum</span></div></div>
        <div class="v2-phone-octo"><img src="/static/images/octo-analyst.webp" alt="Octo"><div><strong>Octo AI Yorumu</strong><br>${why}</div></div>
      </div>
      <div id="modal-performance" class="modal-pane"><div class="mini-chart-phone"><span style="height:70%"></span><span style="height:45%"></span><span style="height:58%"></span><span style="height:42%"></span><span style="height:55%"></span><span style="height:35%"></span><span style="height:22%"></span></div><p class="modal-note">${isComp?'Rakip hareketleri sadece izleme ve alarm için kullanılır.':'Performans değişimi aksiyon önerilerini tetikler.'}</p></div>
      ${isComp?'':`<div id="modal-advice" class="modal-pane"><div class="v2-rule-list"><p>✓ Kreatifi değiştir</p><p>✓ Başlık metnini A/B test et</p><p>✓ Frekans yüksekse bütçeyi düşür</p></div></div>`}
      <div id="modal-history" class="modal-pane"><div class="v2-rule-list"><p>✓ Bugün Octo AI analiz etti</p><p>✓ Son 7 gün karşılaştırıldı</p><p>${isComp?'✓ Rakip gözlem arşivine eklendi':'✓ Reklam aksiyon listesine eklendi'}</p></div></div>
    </div>
    <div class="v2-phone-actions">${isComp?'<button class="blue" onclick="showSpeech(\'Rakip reklamı sadece gözlemlenir. Güncelleme veya müdahale yapılmaz.\')">Gözlem Notu</button><button class="orange" onclick="octoSpeak(\'rakipler\')">Octo Yorumu</button><button class="blue" onclick="closeV2Phone()">Kapat</button>':'<button class="red" onclick="showSpeech(\'Durdurma görevi oluşturuldu.\')">Durdur</button><button class="orange" onclick="showSpeech(\'Bütçe düşürme önerisi oluşturuldu.\')">Bütçeyi Düşür</button><button class="blue" onclick="showSpeech(\'Kreatif değişiklik görevi oluşturuldu.\')">Kreatif Değiştir</button>'}</div>`;
  bindModalTabs();
});
document.addEventListener('click',(e)=>{ if(e.target && e.target.id==='v2PhoneModal') closeV2Phone(); });
document.addEventListener('keydown',(e)=>{ if(e.key==='Escape') closeV2Phone(); });
