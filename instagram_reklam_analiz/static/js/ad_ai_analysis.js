// static/js/ad_ai_analysis.js

class AdAIAnalyzer {
    constructor() {
        this.pollingIntervals = {};
    }

    /**
     * Reklam analizini başlat
     * @param {number} adId - Reklam ID'si
     * @param {HTMLElement} buttonElement - Tıklanan buton
     */
    async startAnalysis(adId, buttonElement) {
        // CSRF token'ı al
        const csrfToken = this.getCsrfToken();
        
        // Butonu devre dışı bırak ve yükleniyor göster
        this.setButtonLoading(buttonElement, true);
        
        try {
            const response = await fetch(`/ad/${adId}/analyze/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                },
                body: JSON.stringify({ ad_id: adId })
            });
            
            const data = await response.json();
            
            if (data.success) {
                // Başarılı - ilerleme takibini başlat
                this.showProgressBar(adId);
                this.startPolling(adId, data.analysis_id);
                
                // Toast mesajı göster
                this.showToast('✅ AI analizi başlatıldı! 12 ajan sırayla çalışacak.', 'success');
            } else {
                // Hata
                this.setButtonLoading(buttonElement, false);
                this.showToast('❌ ' + data.message, 'error');
            }
            
        } catch (error) {
            console.error('Analiz başlatma hatası:', error);
            this.setButtonLoading(buttonElement, false);
            this.showToast('❌ Bağlantı hatası! Lütfen tekrar deneyin.', 'error');
        }
    }

    /**
     * Analiz durumunu periyodik olarak sorgula
     * @param {number} adId 
     * @param {number} analysisId 
     */
    startPolling(adId, analysisId) {
        // Her 2 saniyede bir sorgula
        const intervalId = setInterval(async () => {
            try {
                const response = await fetch(`/analysis/${analysisId}/status/`);
                const data = await response.json();
                
                if (data.success) {
                    // İlerlemeyi güncelle
                    this.updateProgress(adId, data);
                    
                    // Tamamlandı veya hata
                    if (data.status === 'completed') {
                        clearInterval(intervalId);
                        this.showResults(adId, data);
                        this.showToast('🎉 Analiz tamamlandı!', 'success');
                    } else if (data.status === 'failed') {
                        clearInterval(intervalId);
                        this.showToast('❌ Analiz başarısız: ' + data.error_message, 'error');
                    }
                }
                
            } catch (error) {
                console.error('Durum sorgulama hatası:', error);
                clearInterval(intervalId);
            }
        }, 2000);
        
        // Interval ID'sini sakla (iptal etmek için)
        this.pollingIntervals[adId] = intervalId;
    }

    /**
     * İlerleme çubuğunu güncelle
     */
    updateProgress(adId, data) {
        const progressBar = document.querySelector(`#ad-${adId}-progress .progress-bar`);
        const statusText = document.querySelector(`#ad-${adId}-status-text`);
        const currentAgent = document.querySelector(`#ad-${adId}-current-agent`);
        
        if (progressBar) {
            progressBar.style.width = data.progress + '%';
            progressBar.setAttribute('aria-valuenow', data.progress);
            progressBar.textContent = data.progress + '%';
        }
        
        if (statusText) {
            statusText.textContent = this.getStatusText(data.status);
        }
        
        if (currentAgent && data.current_agent) {
            currentAgent.innerHTML = `🔄 Çalışan ajan: <strong>${data.current_agent}</strong>`;
        }
    }

    /**
     * Analiz sonuçlarını göster
     */
    showResults(adId, data) {
        const resultsContainer = document.querySelector(`#ad-${adId}-results`);
        
        if (!resultsContainer || !data.scores) return;
        
        // Skor kartları HTML'i
        const scoresHTML = this.generateScoreCards(data.scores);
        
        // Öneriler HTML'i
        const recommendationsHTML = data.top_recommendations?.length 
            ? this.generateRecommendationsList(data.top_recommendations)
            : '';
        
        // Aksiyon planı HTML'i
        const actionPlanHTML = data.action_plan?.length
            ? this.generateActionPlan(data.action_plan)
            : '';
        
        resultsContainer.innerHTML = `
            <div class="ai-results-container animate__animated animate__fadeIn">
                <!-- Genel Skor -->
                <div class="overall-score-card">
                    <div class="score-circle" style="--score: ${data.scores.overall}">
                        <span class="score-value">${data.scores.overall.toFixed(1)}</span>
                        <span class="score-label">Genel Skor</span>
                    </div>
                    <div class="processing-time">
                        ⏱️ ${data.processing_time.toFixed(1)} saniye
                    </div>
                </div>
                
                <!-- Detaylı Skorlar -->
                <h5 class="mt-4 mb-3">📊 Detaylı Skorlar</h5>
                <div class="row">
                    ${scoresHTML}
                </div>
                
                <!-- Yönetici Özeti -->
                ${data.executive_summary ? `
                <div class="executive-summary mt-4">
                    <h5>📝 Yönetici Özeti</h5>
                    <div class="summary-content">${data.executive_summary.replace(/\n/g, '<br>')}</div>
                </div>
                ` : ''}
                
                <!-- Öneriler -->
                ${recommendationsHTML}
                
                <!-- Aksiyon Planı -->
                ${actionPlanHTML}
            </div>
        `;
        
        // CSS animasyonu için sınıf ekle
        resultsContainer.classList.add('show');
    }

    /**
     * Skor kartlarını oluştur
     */
    generateScoreCards(scores) {
        const scoreItems = [
            { key: 'sentiment', label: 'Duygu', icon: '😊', color: '#ff6b6b' },
            { key: 'content_quality', label: 'İçerik', icon: '📝', color: '#4ecdc4' },
            { key: 'hashtag_effectiveness', label: 'Hashtag', icon: '#️⃣', color: '#45b7d1' },
            { key: 'competitor', label: 'Rekabet', icon: '⚔️', color: '#f9ca24' },
            { key: 'performance', label: 'Performans', icon: '📈', color: '#6c5ce7' },
            { key: 'budget_efficiency', label: 'Bütçe', icon: '💰', color: '#a29bfe' },
            { key: 'lead_potential', label: 'Lead', icon: '🎯', color: '#fd79a8' },
            { key: 'market_fit', label: 'Pazar', icon: '🌍', color: '#00b894' },
        ];
        
        return scoreItems.map(item => {
            const score = scores[item.key] || 0;
            const displayScore = item.key === 'sentiment' 
                ? ((score + 1) * 50).toFixed(0)  // -1..1 -> 0..100
                : score.toFixed(0);
            
            return `
                <div class="col-md-3 col-sm-6 mb-3">
                    <div class="score-card" style="border-left: 3px solid ${item.color}">
                        <div class="score-icon">${item.icon}</div>
                        <div class="score-info">
                            <div class="score-number" style="color: ${item.color}">${displayScore}%</div>
                            <div class="score-title">${item.label}</div>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    }

    /**
     * Öneriler listesini oluştur
     */
    generateRecommendationsList(recommendations) {
        return `
            <div class="recommendations-section mt-4">
                <h5>💡 En Önemli Öneriler</h5>
                <ul class="recommendations-list">
                    ${recommendations.map((rec, index) => `
                        <li class="recommendation-item">
                            <span class="rec-number">${index + 1}</span>
                            <span class="rec-text">${rec}</span>
                        </li>
                    `).join('')}
                </ul>
            </div>
        `;
    }

    /**
     * Aksiyon planını oluştur
     */
    generateActionPlan(actionPlan) {
        return `
            <div class="action-plan-section mt-4">
                <h5>⚡ Aksiyon Planı</h5>
                <div class="action-steps">
                    ${actionPlan.map((step, index) => `
                        <div class="action-step">
                            <div class="step-number">${index + 1}</div>
                            <div class="step-content">${step}</div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }

    /**
     * İlerleme çubuğunu göster
     */
    showProgressBar(adId) {
        const container = document.querySelector(`#ad-${adId}-analysis-container`);
        if (!container) return;
        
        container.innerHTML = `
            <div class="analysis-progress" id="ad-${adId}-progress-container">
                <div class="progress" style="height: 25px;">
                    <div id="ad-${adId}-progress" 
                         class="progress-bar progress-bar-striped progress-bar-animated bg-primary" 
                         role="progressbar" 
                         style="width: 0%">0%</div>
                </div>
                <div id="ad-${adId}-current-agent" class="current-agent-text mt-2">
                    🔄 Başlatılıyor...
                </div>
                <div id="ad-${adId}-results"></div>
            </div>
        `;
    }

    /**
     * Buton durumunu ayarla
     */
    setButtonLoading(button, isLoading) {
        if (isLoading) {
            button.disabled = true;
            button.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Analiz Ediliyor...';
        } else {
            button.disabled = false;
            button.innerHTML = '🤖 AI Analizini Başlat';
        }
    }

    /**
     * CSRF token'ı al
     */
    getCsrfToken() {
        return document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
    }

    /**
     * Toast mesajı göster
     */
    showToast(message, type = 'info') {
        // Bootstrap toast veya basit alert kullanabilirsiniz
        const toastContainer = document.getElementById('toast-container') || this.createToastContainer();
        
        const toastHTML = `
            <div class="toast align-items-center text-bg-${type} border-0" role="alert">
                <div class="d-flex">
                    <div class="toast-body">${message}</div>
                    <button type="button" class="btn-close me-2 m-auto" data-bs-dismiss="toast"></button>
                </div>
            </div>
        `;
        
        toastContainer.insertAdjacentHTML('beforeend', toastHTML);
        const toastElement = toastContainer.lastElementChild;
        const toast = new bootstrap.Toast(toastElement, { delay: 3000 });
        toast.show();
    }

    createToastContainer() {
        const container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
        document.body.appendChild(container);
        return container;
    }

    getStatusText(status) {
        const statusMap = {
            'pending': '⏳ Beklemede',
            'processing': '🔄 Analiz Ediliyor...',
            'completed': '✅ Tamamlandı',
            'failed': '❌ Başarısız'
        };
        return statusMap[status] || status;
    }
}

// Global instance
const adAnalyzer = new AdAIAnalyzer();