/* Global layout behavior extracted from core/templates/base.html. */

window.raFormatNumber = function(value, fractionDigits = 2) {
    const number = Number.parseFloat(value);
    const safeNumber = Number.isFinite(number) ? number : 0;
    return new Intl.NumberFormat('tr-TR', {
        minimumFractionDigits: fractionDigits,
        maximumFractionDigits: fractionDigits
    }).format(safeNumber);
};

window.raFormatMoney = function(value) {
    return `₺${window.raFormatNumber(value, 2)}`;
};

window.raFormatPercent = function(value) {
    return `%${window.raFormatNumber(value, 2)}`;
};

function showToast(message, type = 'success', title = '') {
            const container = document.getElementById('globalToastContainer');
            if (!container) return;
            const titles = { success: '✅ Başarılı', error: '❌ Hata', warning: '⚠️ Uyarı', info: 'ℹ️ Bilgi' };
            const icons = { success: 'fa-check-circle', error: 'fa-exclamation-circle', warning: 'fa-exclamation-triangle', info: 'fa-info-circle' };
            const toast = document.createElement('div');
            toast.className = `toast-global toast-global-${type}`;
            toast.innerHTML = `<div class="toast-global-content"><div class="toast-global-icon"><i class="fas ${icons[type] || icons.info}"></i></div><div class="toast-global-message"><strong>${titles[type] || titles.info} ${title ? `- ${title}` : ''}</strong><div>${message}</div></div></div><div class="toast-global-progress"></div>`;
            container.appendChild(toast);
            setTimeout(() => toast.remove(), 3200);
        }
        function checkUrlForMessage() {
            const urlParams = new URLSearchParams(window.location.search);
            const message = urlParams.get('message');
            const error = urlParams.get('error');
            if (message) { showToast(decodeURIComponent(message), 'success', 'Bilgi'); window.history.replaceState({}, document.title, window.location.pathname); }
            if (error) { showToast(decodeURIComponent(error), 'error', 'Hata'); window.history.replaceState({}, document.title, window.location.pathname); }
        }
        function toggleAlertPanel(event) {
            event.preventDefault(); event.stopPropagation();
            document.querySelectorAll('.nav-item.dropdown.open, .user-menu.open').forEach(el => el.classList.remove('open'));
            document.getElementById('alertDropdownPanel')?.classList.toggle('show');
        }
        function closeAlertPanel() { document.getElementById('alertDropdownPanel')?.classList.remove('show'); }
        function dismissSingleAlert(dbId, alertDomId) {
            fetch('/api/alerts/dismiss/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCookie('csrftoken'),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ notification_id: dbId })
            })
            .then(() => {
                const item = document.getElementById('alert-' + alertDomId);
                if (item) item.remove();

                const badge = document.getElementById('alertCountBadge');
                if (badge) {
                    const current = parseInt(badge.textContent || '0', 10);
                    const next = Math.max(current - 1, 0);
                    if (next > 0) badge.textContent = next;
                    else badge.remove();
                }
            });
        }
        function getCookie(name) {
            let v = `; ${document.cookie}`; let parts = v.split(`; ${name}=`);
            if (parts.length === 2) return parts.pop().split(';').shift(); return null;
        }
        function escapeHtml(value) {
            const div = document.createElement('div');
            div.textContent = value || '';
            return div.innerHTML;
        }
        function normalizeToastType(level) {
            if (level === 'critical') return 'error';
            if (level === 'warning') return 'warning';
            if (level === 'success') return 'success';
            return 'info';
        }
        function renderNotificationIcon(value) {
            const raw = String(value || '').trim();
            const aliases = {
                'chart-line': 'fa-chart-line', 'chart_line': 'fa-chart-line', 'line-chart': 'fa-chart-line',
                'bell': 'fa-bell', 'warning': 'fa-triangle-exclamation', 'error': 'fa-circle-exclamation',
                'success': 'fa-circle-check', 'info': 'fa-circle-info', 'bullhorn': 'fa-bullhorn'
            };
            let icon = raw.toLowerCase().replace(/^(fas|far|fab)\s+/, '');
            icon = aliases[icon] || icon;
            if (/^fa-[a-z0-9-]+$/.test(icon)) return `<i class="fas ${icon}" aria-hidden="true"></i>`;
            if (!raw || /^[\x00-\x7F]+$/.test(raw)) return '<i class="fas fa-bell" aria-hidden="true"></i>';
            return escapeHtml(Array.from(raw).slice(0, 4).join(''));
        }
        function getCurrentAlertBadgeCount() {
            const badge = document.getElementById('alertCountBadge');
            return parseInt((badge && badge.textContent) || '0', 10) || 0;
        }
        function setAlertBadgeCount(value) {
            const bell = document.querySelector('.alert-bell-btn');
            let badge = document.getElementById('alertCountBadge');
            const next = Math.max(parseInt(value || 0, 10) || 0, 0);
            if (!bell) return;
            if (next <= 0) {
                if (badge) badge.remove();
                return;
            }
            if (!badge) {
                badge = document.createElement('span');
                badge.className = 'alert-count-badge';
                badge.id = 'alertCountBadge';
                bell.appendChild(badge);
            }
            badge.textContent = String(next);
        }
        function incrementAlertBadge() {
            setAlertBadgeCount(getCurrentAlertBadgeCount() + 1);
        }
        function prependRealtimeNotification(notification, options = {}) {
            const container = document.getElementById('alertListContainer');
            if (!container || !notification || !notification.id) return;
            const existing = document.getElementById('alert-notification_' + notification.id) || document.getElementById('alert-notification-' + notification.id);
            if (existing) return;

            const emptyState = container.querySelector('.alert-empty-state, .text-center');
            if (emptyState) emptyState.remove();

            const item = document.createElement('div');
            const isAnnouncement = String(notification.icon || '').trim().toLowerCase() === 'bullhorn';
            item.className = isAnnouncement ? 'alert-item announcement' : 'alert-item';
            item.id = 'alert-notification_' + notification.id;
            item.innerHTML = `
                <a href="/bildirimler/${encodeURIComponent(notification.id)}/ac/" class="alert-item-link" onclick="closeAlertPanel()">
                    <span class="alert-item-icon">${renderNotificationIcon(notification.icon)}</span>
                    <div class="alert-item-content">
                        <div class="alert-item-title ${escapeHtml(notification.level || 'info')}">${escapeHtml(notification.title)}</div>
                        <div class="alert-item-msg">${escapeHtml((notification.message || '').slice(0, 75))}</div>
                        <div class="alert-item-time">az önce</div>
                    </div>
                </a>
                <button class="alert-dismiss-btn" onclick="dismissSingleAlert('${notification.id}', 'notification_${notification.id}')">✕</button>
            `;
            container.prepend(item);

            if (options.incrementBadge !== false && notification.is_read !== true) incrementAlertBadge();
            if (options.showToast !== false) showToast(notification.message || '', normalizeToastType(notification.level), notification.title || 'Yeni Bildirim');
        }

        let latestNotificationId = 0;
        const shownRealtimeNotifications = new Set();

        function rememberExistingNotificationIds() {
            document.querySelectorAll('.alert-item').forEach(el => {
                const rawId = el.id || '';
                let id = null;

                // Yeni JS ile eklenenler: alert-notification_123
                let match = rawId.match(/alert-notification[_-](\d+)/);
                if (match) id = parseInt(match[1], 10);

                // Template'ten gelenler: id="alert-notification_123" veya onclick="dismissSingleAlert('123', ...)"
                if (!id) {
                    const btn = el.querySelector('.alert-dismiss-btn');
                    const onclickText = btn ? (btn.getAttribute('onclick') || '') : '';
                    match = onclickText.match(/dismissSingleAlert\(['"]?(\d+)['"]?/);
                    if (match) id = parseInt(match[1], 10);
                }

                if (!Number.isNaN(id) && id) {
                    latestNotificationId = Math.max(latestNotificationId, id);
                    shownRealtimeNotifications.add(String(id));
                }
            });
        }

        function handleIncomingNotification(notification, source = 'unknown') {
            if (!notification || !notification.id) return;
            const id = String(notification.id);
            latestNotificationId = Math.max(latestNotificationId, parseInt(id, 10) || 0);

            if (shownRealtimeNotifications.has(id)) return;
            if (document.getElementById('alert-notification_' + id) || document.getElementById('alert-notification-' + id)) {
                shownRealtimeNotifications.add(id);
                return;
            }

            shownRealtimeNotifications.add(id);
            prependRealtimeNotification(notification, {
                incrementBadge: true,
                showToast: source !== 'initial-poll'
            });
        }

        let notificationSocket = null;
        let notificationSocketConnected = false;
        const notificationsEnabled = window.__reklamAnalizUserAuthenticated === true;
        let notificationSocketRetryTimer = null;

        function connectNotificationSocket() {
            if (!notificationsEnabled) return;
            if (!window.WebSocket) return;
            if (notificationSocket && [WebSocket.OPEN, WebSocket.CONNECTING].includes(notificationSocket.readyState)) return;

            const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
            const socketUrl = `${protocol}://${window.location.host}/ws/notifications/`;
            try { notificationSocket = new WebSocket(socketUrl); }
            catch (e) { console.warn('Bildirim WebSocket oluşturulamadı', e); return; }

            notificationSocket.onopen = function() {
                notificationSocketConnected = true;
                console.log('Bildirim WebSocket bağlandı');
            };
            notificationSocket.onmessage = function(event) {
                try {
                    const data = JSON.parse(event.data);
                    console.log('Bildirim WebSocket mesajı', data);
                    if (data.type === 'notification.created') handleIncomingNotification(data.notification, 'websocket');
                } catch (e) { console.warn('Bildirim mesajı okunamadı', e); }
            };
            notificationSocket.onerror = function(event) { if (notificationsEnabled) console.warn('Bildirim WebSocket hatası', event); };
            notificationSocket.onclose = function(event) {
                notificationSocketConnected = false;
                if (!notificationsEnabled) return;
                if (event && event.code === 1008) return;
                console.warn('Bildirim WebSocket kapandı, tekrar denenecek');
                clearTimeout(notificationSocketRetryTimer);
                notificationSocketRetryTimer = setTimeout(connectNotificationSocket, 15000);
            };
        }

        let notificationPollRunning = false;
        function pollLatestNotifications(source = 'poll') {
            if (!notificationsEnabled) return;
            if (notificationPollRunning) return;
            notificationPollRunning = true;
            fetch(`/api/notifications/latest/?after_id=${latestNotificationId}`, {
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
                cache: 'no-store'
            })
            .then(r => r.ok ? r.json() : null)
            .then(data => {
                if (!data || !data.notifications) return;
                data.notifications.forEach(n => handleIncomingNotification(n, source));
            })
            .catch(() => {})
            .finally(() => { notificationPollRunning = false; });
        }

        function closeAllDropdowns(except = null) {
            document.querySelectorAll('.nav-item.dropdown.open, .user-menu.open').forEach(el => { if (el !== except) el.classList.remove('open'); });
        }
        document.addEventListener('DOMContentLoaded', function() {
            checkUrlForMessage();
            if (!window.__reklamAnalizNotificationsStarted) {
                window.__reklamAnalizNotificationsStarted = true;
                if (notificationsEnabled) {
                    rememberExistingNotificationIds();
                    connectNotificationSocket();
                    pollLatestNotifications('initial-poll');
                    setInterval(() => pollLatestNotifications('poll'), 30000);
                }
            }
            const mobileBtn = document.getElementById('mobileMenuBtn');
            const navbarMenu = document.getElementById('navbarMenu');
            const sidebarBackdrop = document.getElementById('sidebarBackdrop');
            if (mobileBtn && navbarMenu) mobileBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                const willOpen = !navbarMenu.classList.contains('active');
                navbarMenu.classList.toggle('active', willOpen);
                if (sidebarBackdrop) sidebarBackdrop.classList.toggle('show', willOpen);
                closeAllDropdowns();
                closeAlertPanel();
            });
            if (sidebarBackdrop) sidebarBackdrop.addEventListener('click', () => { navbarMenu?.classList.remove('active'); sidebarBackdrop.classList.remove('show'); });

            document.querySelectorAll('.nav-item.dropdown > .nav-link.dropdown-toggle').forEach(trigger => {
                trigger.addEventListener('click', function(e) {
                    e.preventDefault(); e.stopPropagation();
                    closeAlertPanel();
                    const parent = this.closest('.nav-item.dropdown');
                    const willOpen = !parent.classList.contains('open');
                    closeAllDropdowns(parent);
                    parent.classList.toggle('open', willOpen);
                });
            });

            const userMenu = document.querySelector('.user-menu');
            if (userMenu) userMenu.addEventListener('click', function(e) { e.stopPropagation(); closeAlertPanel(); const willOpen = !this.classList.contains('open'); closeAllDropdowns(this); this.classList.toggle('open', willOpen); });

            document.addEventListener('click', (e) => {
                const panel = document.getElementById('alertDropdownPanel');
                const bell = document.querySelector('.alert-bell-btn');
                if (panel && bell && !bell.contains(e.target) && !panel.contains(e.target)) panel.classList.remove('show');
                if (!e.target.closest('.nav-item.dropdown') && !e.target.closest('.user-menu')) closeAllDropdowns();
                if (navbarMenu && !e.target.closest('.navbar') && !e.target.closest('.ra-sidebar') && navbarMenu.classList.contains('active')) { navbarMenu.classList.remove('active'); sidebarBackdrop?.classList.remove('show'); }
            });

            document.querySelectorAll('.dropdown-item-nav').forEach(item => {
                item.addEventListener('click', function() {
                    closeAllDropdowns();
                    if (navbarMenu) navbarMenu.classList.remove('active');
                    sidebarBackdrop?.classList.remove('show');
                });
            });
        });
