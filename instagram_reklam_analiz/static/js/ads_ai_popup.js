(function () {
  const trNumber = (value, digits = 2) => new Intl.NumberFormat('tr-TR', {minimumFractionDigits: digits, maximumFractionDigits: digits}).format(Number(value || 0));
  const trInt = (value) => new Intl.NumberFormat('tr-TR', {maximumFractionDigits: 0}).format(Number(value || 0));
  const trDateTime = (value) => value ? new Intl.DateTimeFormat('tr-TR', {dateStyle:'short', timeStyle:'short'}).format(new Date(value)) : '';
  const trMoney = (value) => `${trNumber(value, 2)} TL`;
  const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#039;','"':'&quot;'}[c]));
  const severityLabel = value => ({critical:'Kritik', warning:'Uyarı', info:'Bilgi', opportunity:'Fırsat'}[String(value || '').toLowerCase()] || value || 'Bilgi');
  let activeAdId = null;
  let activeDetail = null;

  function scopedUrl(path) {
    const url = new URL(path, window.location.origin);
    const scope = window.adsPanelAgencyClientScope || '';
    if (scope) url.searchParams.set('agency_client', scope);
    return url.pathname + (url.search ? url.search : '');
  }

  function ensureModal() {
    if (document.getElementById('adAiBackdrop')) return;
    document.body.insertAdjacentHTML('beforeend', `
      <div class="ad-ai-backdrop" id="adAiBackdrop">
        <div class="ad-ai-modal" role="dialog" aria-modal="true" aria-labelledby="adAiTitle">
          <header class="ad-ai-head"><div><h2 id="adAiTitle">Reklam Intelligence</h2><p id="adAiSubtitle">Veritabanı metrikleri · kreatif · tespitler · 16 ajan</p></div><button class="ad-ai-close" type="button" aria-label="Kapat">×</button></header>
          <div class="ad-ai-body" id="adAiBody"></div>
        </div>
      </div>`);
    document.querySelector('.ad-ai-close').addEventListener('click', closeAdAiPopup);
    document.getElementById('adAiBackdrop').addEventListener('click', e => { if (e.target.id === 'adAiBackdrop') closeAdAiPopup(); });
  }

  function metric(label, value) { return `<div class="ad-ai-metric"><span>${esc(label)}</span><b>${value}</b></div>`; }
  function identity(label, value) { return `<div><span>${esc(label)}</span><b title="${esc(value)}">${esc(value || '-')}</b></div>`; }

  function reportCard(type, report) {
    const title = type === 'analysis' ? 'AI Analiz' : 'AI Öneri';
    if (!report) return `<article class="ad-ai-report" id="adAiReport-${type}"><header><strong>${title}</strong></header><div class="ad-ai-empty">Henüz kayıt yok. İlk çalıştırmada sonuç veritabanına kaydedilir.</div></article>`;
    const toPoints = value => String(value || '').replace(/([.!?])\s+/g, '$1\n').split(/\r?\n+/).map(line => line.trim()).filter(Boolean);
    let points = (report.agents || []).flatMap(a => toPoints(
      type === 'analysis'
        ? (a.finding || a.reason || a.status)
        : (a.recommendation || a.status)
    ));
    if (!points.length) points = toPoints(report.summary || 'Sonuç kaydı oluşturuldu.').map(line => line.replace(/^[^:]{1,80}:\s*/, '').trim()).filter(Boolean);
    const pointList = points.map(point => `<li>${esc(point)}</li>`).join('');
    return `<article class="ad-ai-report" id="adAiReport-${type}"><header><strong>${title} · ${report.score}/100</strong><time>${esc(report.created_label)}</time></header><ul class="ad-ai-point-list">${pointList}</ul></article>`;
  }

  function render(detail) {
    if ((window.adsPopupConfig || {}).mode === 'competitor') {
      renderCompetitor(detail);
      return;
    }
    activeDetail = detail;
    const m = detail.metrics || {};
    const c = detail.creative || {};
    const media = c.video_url
      ? `<video src="${esc(c.video_url)}" poster="${esc(c.thumbnail_url || c.image_url)}" controls playsinline></video>`
      : c.image_url ? `<img src="${esc(c.image_url)}" alt="${esc(detail.name)}">` : '<i class="fas fa-image fa-3x"></i>';
    const rules = (detail.rules || []).map(r => `<div class="ad-ai-rule"><span class="ad-ai-rule-severity ${esc(r.severity)}">${esc(severityLabel(r.severity))}</span><div><strong>${esc(r.title)}</strong><small class="ad-ai-rule-scope">${esc(r.scope_label || 'Kural')} kapsamı${r.source_period_start && r.source_period_end ? ` · ${esc(r.source_period_start)} – ${esc(r.source_period_end)}` : ''}</small><p>${esc(r.message || '')}</p>${r.action ? `<p><b>Aksiyon:</b> ${esc(r.action)}</p>` : ''}</div></div>`).join('');
    const engine = detail.rule_engine || {};
    const engineLabel = engine.status === 'completed'
      ? `Son tarama · ${trDateTime(engine.last_run_at)}`
      : engine.status === 'failed' ? 'Tarama hatası' : engine.status === 'running' ? 'Tarama sürüyor' : 'Tarama bekleniyor';
    document.getElementById('adAiTitle').textContent = detail.name;
    document.getElementById('adAiBody').innerHTML = `
      <div class="ad-ai-overview">
        <article class="ad-ai-creative"><div class="ad-ai-media">${media}</div><div class="ad-ai-creative-copy"><div class="ad-ai-chip">${esc(c.type || 'Kreatif')}</div>${c.call_to_action ? `<div class="ad-ai-chip">CTA · ${esc(c.call_to_action)}</div>` : ''}</div></article>
        <article class="ad-ai-panel"><div class="ad-ai-identity">${identity('Platform',detail.platform)}${identity('Hesap',detail.account)}${identity('Kampanya',detail.campaign)}${identity('Reklam grubu',detail.ad_group)}${identity('Amaç',detail.objective)}${identity('Durum',detail.status_label)}</div><div class="ad-ai-metrics">${metric('Harcama',trMoney(m.spend))}${metric('Gelir',trMoney(m.conversion_value))}${metric('ROAS',trNumber(m.roas)+'x')}${metric('Gösterim',trInt(m.impressions))}${metric('Tıklama',trInt(m.clicks))}${metric('CTR','%'+trNumber(m.ctr))}${metric('CPC',trMoney(m.cpc))}${metric('CPM',trMoney(m.cpm))}${metric('Dönüşüm',trNumber(m.conversions))}${metric('CPA',trMoney(m.cpa))}${metric('Erişim',trInt(m.reach))}${metric('Frekans',trNumber(m.frequency))}${metric('Etkileşim',trInt(m.engagement))}${metric('Kayıt günü',trInt(m.row_count))}${metric('Performans',detail.performance_score+'/100')}</div></article>
      </div>
      <section class="ad-ai-section"><div class="ad-ai-section-head"><h3>Tespitler</h3><div class="ad-ai-rule-stats"><span class="ad-ai-chip">${trInt(detail.active_rule_count)} kural kataloğu</span><span class="ad-ai-chip">${trInt(detail.matched_rule_count)} eşleşme</span><span class="ad-ai-chip">${esc(engineLabel)}</span></div></div><div class="ad-ai-rules">${rules || '<div class="ad-ai-empty">Tarama tamamlandı; bu reklam için açık tespit bulunmuyor.</div>'}</div></section>
      <section class="ad-ai-section"><div class="ad-ai-section-head"><h3>Yapay Zeka Analiz ve Öneri Alanı</h3><div class="ad-ai-actions"><button class="ad-ai-run analysis" data-report-type="analysis"><i class="fas fa-brain"></i> AI Analiz Çalıştır</button><button class="ad-ai-run recommendation" data-report-type="recommendation"><i class="fas fa-lightbulb"></i> AI Öneri Çalıştır</button></div></div><div id="adAiError"></div><div class="ad-ai-report-grid">${reportCard('analysis',detail.latest_reports?.analysis)}${reportCard('recommendation',detail.latest_reports?.recommendation)}</div></section>`;
    document.querySelectorAll('.ad-ai-run').forEach(btn => btn.addEventListener('click', () => runAdAiReport(btn.dataset.reportType, btn)));
  }

  function renderCompetitor(detail) {
    activeDetail = detail;
    const m = detail.metrics || {};
    const image = detail.preview_image_url || '';
    const video = detail.preview_video_url || '';
    const media = video
      ? `<video src="${esc(video)}" poster="${esc(image)}" controls playsinline></video>`
      : image ? `<img src="${esc(image)}" alt="${esc(detail.name)}">`
      : '<div class="ad-ai-empty"><i class="fas fa-photo-film fa-3x"></i><p>Canlı kaynak bu reklam için indirilebilir bir görsel sağlamadı.</p></div>';
    const copyItems = [
      ['Başlık', detail.headline],
      ['Reklam metni', detail.primary_text],
      ['Açıklama', detail.description],
      ['Eylem çağrısı', detail.call_to_action],
    ].filter(item => item[1]).map(item => `<div class="ad-ai-rule"><span class="ad-ai-rule-severity info"><i class="fas fa-circle"></i></span><div><strong>${esc(item[0])}</strong><p>${esc(item[1])}</p></div></div>`).join('');
    const sourceMetrics = detail.has_live_metrics ? [
      Number(m.impressions || 0) ? metric('Gösterim tahmini', trInt(m.impressions)) : '',
      Number(m.spend || 0) ? metric('Harcama tahmini', trMoney(m.spend)) : '',
    ].join('') : '';
    document.getElementById('adAiTitle').textContent = detail.name;
    document.getElementById('adAiSubtitle').textContent = 'Canlı rakip reklam kaynağından doğrulanan bilgiler';
    document.getElementById('adAiBody').innerHTML = `
      <div class="ad-ai-overview">
        <article class="ad-ai-creative"><div class="ad-ai-media">${media}</div><div class="ad-ai-creative-copy"><div class="ad-ai-chip">${esc(detail.ad_format || 'Reklam')}</div></div></article>
        <article class="ad-ai-panel">
          <div class="ad-ai-identity">${identity('Rakip',detail.competitor_name)}${identity('Platform',detail.platform_name)}${identity('Durum',String(detail.status || '').toUpperCase() === 'ACTIVE' ? 'Aktif' : 'Yayını sona erdi')}${identity('İlk görülme',detail.first_seen_at)}${identity('Son görülme',detail.last_seen_at)}</div>
          ${sourceMetrics ? `<div class="ad-ai-metrics">${sourceMetrics}</div><small class="ad-ai-empty">Bu değerler ${esc(detail.metric_source_label || 'kaynak aralığı')} orta noktasıdır; kesin sonuç değildir.</small>` : '<div class="ad-ai-empty">Canlı kaynak bu reklam için performans metriği yayınlamıyor.</div>'}
        </article>
      </div>
      <section class="ad-ai-section"><div class="ad-ai-section-head"><h3>Canlı reklam içeriği</h3></div><div class="ad-ai-rules">${copyItems || '<div class="ad-ai-empty">Kaynakta ek reklam metni bulunmuyor.</div>'}</div></section>
      ${detail.landing_url ? `<section class="ad-ai-section"><a class="ad-ai-run analysis" href="${esc(detail.landing_url)}" target="_blank" rel="noopener noreferrer"><i class="fas fa-up-right-from-square"></i> Reklamı canlı kaynakta aç</a></section>` : ''}`;
  }

  async function runAdAiReport(type, button) {
    const errorBox = document.getElementById('adAiError');
    errorBox.innerHTML = '';
    document.querySelectorAll('.ad-ai-run').forEach(b => b.disabled = true);
    const old = button.innerHTML;
    button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 16 ajan çalışıyor...';
    try {
      const response = await fetch(scopedUrl(`/api/reklamlar/${activeAdId}/ai/${type}/`), {method:'POST', headers:{'X-CSRFToken': window.adsPanelCsrfToken || '', 'X-Requested-With':'XMLHttpRequest','Accept':'application/json'}});
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.message || 'AI çalışması tamamlanamadı.');
      activeDetail.latest_reports[type] = data.report;
      document.getElementById(`adAiReport-${type}`).outerHTML = reportCard(type, data.report);
    } catch (error) {
      errorBox.innerHTML = `<div class="ad-ai-error">${esc(error.message)}</div>`;
    } finally {
      document.querySelectorAll('.ad-ai-run').forEach(b => b.disabled = false);
      button.innerHTML = old;
    }
  }

  async function loadAdDetail(adId) {
    const config = window.adsPopupConfig || {};
    const detailPath = typeof config.detailUrl === 'function' ? config.detailUrl(adId) : `/api/reklamlar/${adId}/detail/`;
    const response = await fetch(scopedUrl(detailPath), {headers:{'X-Requested-With':'XMLHttpRequest','Accept':'application/json'}});
    const data = await response.json();
    if (!response.ok || !data.success) throw new Error(data.message || 'Reklam detayı yüklenemedi.');
    return data.ad;
  }

  async function triggerAndRefreshRuleScan(adId, previousRunAt) {
    try {
      const scanResponse = await fetch(scopedUrl(`/api/reklamlar/${adId}/rule-scan/`), {
        method: 'POST',
        headers: {'X-CSRFToken': window.adsPanelCsrfToken || '', 'X-Requested-With':'XMLHttpRequest','Accept':'application/json'}
      });
      const scanData = await scanResponse.json();
      if (!scanResponse.ok || !scanData.success) throw new Error(scanData.message || 'Kural taraması başlatılamadı.');

      for (let attempt = 0; attempt < 10; attempt += 1) {
        await new Promise(resolve => setTimeout(resolve, 2500));
        if (activeAdId !== adId || !document.getElementById('adAiBackdrop')?.classList.contains('show')) return;
        const detail = await loadAdDetail(adId);
        render(detail);
        const currentRunAt = detail.rule_engine?.last_run_at || '';
        if (detail.rule_engine?.status === 'completed' && currentRunAt && currentRunAt !== previousRunAt) return;
        if (detail.rule_engine?.status === 'failed') return;
      }
    } catch (error) {
      const errorBox = document.getElementById('adAiError');
      if (errorBox) errorBox.innerHTML = `<div class="ad-ai-error">${esc(error.message)}</div>`;
    }
  }

  window.openAIPopup = async function (adId) {
    ensureModal(); activeAdId = adId;
    document.getElementById('adAiBackdrop').classList.add('show'); document.body.style.overflow = 'hidden';
    document.getElementById('adAiBody').innerHTML = '<div class="ad-ai-loading"><div><div class="ad-ai-spinner"></div><p>Reklamın veritabanı geçmişi, kreatifi ve kural tespitleri hazırlanıyor...</p></div></div>';
    try {
      const detail = await loadAdDetail(adId);
      render(detail);
      if (window.adsPanelAutoRuleScan && (window.adsPopupConfig || {}).mode !== 'competitor') {
        triggerAndRefreshRuleScan(adId, detail.rule_engine?.last_run_at || '');
      }
    } catch (error) { document.getElementById('adAiBody').innerHTML = `<div class="ad-ai-error">${esc(error.message)}</div>`; }
  };
  window.closeAdAiPopup = function () { document.getElementById('adAiBackdrop')?.classList.remove('show'); document.body.style.overflow = ''; };
  document.addEventListener('keydown', e => { if (e.key === 'Escape') window.closeAdAiPopup(); });
})();
