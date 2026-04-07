function toggleDarkMode() {
    fetch('/toggle-dark-mode', { method: 'POST', headers: { 'X-CSRFToken': getCSRFToken() } })
        .then(() => {
            const html = document.documentElement;
            const current = html.getAttribute('data-theme');
            html.setAttribute('data-theme', current === 'dark' ? 'light' : 'dark');
        });
}

function getCSRFToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
}

// auto-dismiss flash messages after 4 seconds
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.flash').forEach(flash => {
        setTimeout(() => flash.remove(), 4000);
    });
});

function toggleMobileNav() {
    const nav = document.getElementById('nav-links');
    nav.classList.toggle('nav-open');
}

function toggleProfileMenu() {
    const menu = document.getElementById('profile-menu');
    menu.classList.toggle('profile-menu--open');
}

// close on outside click
document.addEventListener('click', function (e) {
    const dropdown = document.querySelector('.profile-dropdown');
    if (dropdown && !dropdown.contains(e.target)) {
        const menu = document.getElementById('profile-menu');
        if (menu) menu.classList.remove('profile-menu--open');
    }
});