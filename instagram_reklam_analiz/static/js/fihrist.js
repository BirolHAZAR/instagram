(function () {
    const search = document.getElementById('glossarySearch');
    const clear = document.getElementById('glossaryClear');
    const items = Array.from(document.querySelectorAll('.glossary-item'));
    const categoryButtons = Array.from(document.querySelectorAll('.glossary-category'));
    const resultCount = document.getElementById('glossaryResultCount');
    const activeFilter = document.getElementById('glossaryActiveFilter');
    const empty = document.getElementById('glossaryEmpty');
    let selectedCategory = 'all';

    function normalize(value) {
        return String(value || '')
            .toLocaleLowerCase('tr-TR')
            .normalize('NFD')
            .replace(/[\u0300-\u036f]/g, '')
            .replace(/ı/g, 'i');
    }

    function filterTerms() {
        const query = normalize(search.value.trim());
        let visible = 0;

        items.forEach(function (item) {
            const categoryMatches = selectedCategory === 'all' || item.dataset.category === selectedCategory;
            const queryMatches = !query || normalize(item.dataset.search).includes(query);
            const show = categoryMatches && queryMatches;
            item.hidden = !show;
            if (show) visible += 1;
        });

        clear.hidden = !search.value;
        resultCount.textContent = String(visible);
        empty.hidden = visible !== 0;
    }

    search.addEventListener('input', filterTerms);
    clear.addEventListener('click', function () {
        search.value = '';
        search.focus();
        filterTerms();
    });

    categoryButtons.forEach(function (button) {
        button.addEventListener('click', function () {
            selectedCategory = button.dataset.category;
            categoryButtons.forEach(function (candidate) {
                const active = candidate === button;
                candidate.classList.toggle('active', active);
                candidate.setAttribute('aria-pressed', String(active));
            });
            activeFilter.textContent = selectedCategory === 'all' ? 'Tüm kategoriler' : selectedCategory;
            filterTerms();
        });
    });
})();
