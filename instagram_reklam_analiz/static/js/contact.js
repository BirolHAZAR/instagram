document.getElementById('contactForm')?.addEventListener('submit', function(e) {
        const requiredFields = this.querySelectorAll('[required]');
        let valid = true;
        requiredFields.forEach(field => {
            if (!field.value.trim()) valid = false;
        });
        if (!valid) {
            e.preventDefault();
            alert('Lütfen tüm alanları doldurun.');
        }
    });
