document.addEventListener('DOMContentLoaded', function() {
    const toggles = document.querySelectorAll('.billing-toggle');
    const monthlyPrices = document.querySelectorAll('.monthly-price');
    const yearlyPrices = document.querySelectorAll('.yearly-price');
    const monthlyKdv = document.querySelectorAll('.monthly-kdv');
    const yearlyKdv = document.querySelectorAll('.yearly-kdv');
    const yearlySavings = document.querySelectorAll('.yearly-savings');
    const billingOptions = document.querySelectorAll('.billing-option');
    if (!toggles.length) return;
    function updateBilling(isYearly) {
        const billing = isYearly ? 'yearly' : 'monthly';
        toggles.forEach(toggle => { toggle.checked = isYearly; });
        billingOptions.forEach(opt => {
            opt.classList.remove('active');
            if ((isYearly && opt.dataset.billing === 'yearly') || (!isYearly && opt.dataset.billing === 'monthly')) opt.classList.add('active');
        });
        monthlyPrices.forEach(el => el.style.display = isYearly ? 'none' : 'inline');
        yearlyPrices.forEach(el => el.style.display = isYearly ? 'inline' : 'none');
        monthlyKdv.forEach(el => el.style.display = isYearly ? 'none' : 'inline');
        yearlyKdv.forEach(el => el.style.display = isYearly ? 'inline' : 'none');
        yearlySavings.forEach(el => el.style.display = isYearly ? 'block' : 'none');
        document.querySelectorAll('a[href*="/checkout/"]').forEach(link => {
            if (link.href.includes('/checkout/ai-kredi/') || link.href.includes('/checkout/urun-arastirma/')) return;
            const url = new URL(link.href, window.location.origin);
            url.searchParams.set('billing', billing);
            link.href = url.toString();
        });
    }
    toggles.forEach(toggle => toggle.addEventListener('change', function() { updateBilling(this.checked); }));
    billingOptions.forEach(option => option.addEventListener('click', function() { updateBilling(this.dataset.billing === 'yearly'); }));
});
