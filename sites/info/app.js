(() => {
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const search = document.getElementById('commandSearch');
  const list = document.getElementById('commandList');
  const count = document.getElementById('searchCount');
  const progress = document.getElementById('scrollProgress');
  const backToTop = document.getElementById('backToTop');
  const mobileNav = document.querySelector('.mobile-nav');

  // Keep the page position visible and provide a quick return to the top.
  const updateScrollUI = () => {
    const scrollable = document.documentElement.scrollHeight - window.innerHeight;
    const percent = scrollable > 0 ? (window.scrollY / scrollable) * 100 : 0;
    if (progress) progress.style.width = `${Math.min(100, Math.max(0, percent))}%`;
    if (backToTop) backToTop.classList.toggle('is-visible', window.scrollY > 520);
  };
  window.addEventListener('scroll', updateScrollUI, { passive: true });
  window.addEventListener('resize', updateScrollUI);
  updateScrollUI();
  backToTop?.addEventListener('click', () => window.scrollTo({ top: 0, behavior: reduceMotion ? 'auto' : 'smooth' }));
  mobileNav?.querySelectorAll('a').forEach(link => link.addEventListener('click', () => { mobileNav.open = false; }));

  // Reveal content as it enters the viewport; keep everything visible if unsupported.
  const revealTargets = document.querySelectorAll('.section, .workflow-inner, .feature-card, .closing-cta');
  if (!reduceMotion && 'IntersectionObserver' in window) {
    const observer = new IntersectionObserver((entries, obs) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          obs.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12 });
    revealTargets.forEach(element => {
      element.classList.add('reveal');
      observer.observe(element);
    });
  }

  if (search && list && count) {
    const rows = [...list.querySelectorAll('.command-row')];
    const updateSearch = () => {
      const query = search.value.trim().toLocaleLowerCase('ru');
      let visible = 0;
      rows.forEach(row => {
        const match = row.textContent.toLocaleLowerCase('ru').includes(query);
        row.hidden = !match;
        if (match) visible += 1;
      });
      count.textContent = query ? `Найдено команд: ${visible}` : 'Показаны все команды';
      count.setAttribute('aria-label', query ? `Найдено команд: ${visible}` : `Всего команд: ${visible}`);
    };
    search.addEventListener('input', updateSearch);
    document.addEventListener('keydown', event => {
      if (event.key === '/' && !event.ctrlKey && !event.metaKey && !event.altKey &&
          !['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
        event.preventDefault();
        search.focus();
      }
      if (event.key === 'Escape' && document.activeElement === search) {
        search.value = '';
        updateSearch();
        search.blur();
      }
    });
  }

  document.querySelectorAll('.copy-command').forEach(button => {
    button.addEventListener('click', async () => {
      const command = button.closest('.command-row')?.querySelector('code')?.textContent?.trim();
      if (!command) return;
      const original = button.textContent;
      try {
        if (navigator.clipboard && window.isSecureContext) {
          await navigator.clipboard.writeText(command);
        } else {
          const field = document.createElement('textarea');
          field.value = command;
          field.setAttribute('readonly', '');
          field.style.position = 'absolute';
          field.style.left = '-9999px';
          document.body.appendChild(field);
          field.select();
          const copied = document.execCommand('copy');
          field.remove();
          if (!copied) throw new Error('Clipboard unavailable');
        }
        button.textContent = 'Скопировано';
        button.dataset.state = 'success';
        button.setAttribute('aria-label', `Скопировано: ${command}`);
      } catch {
        button.textContent = 'Не удалось';
        button.dataset.state = 'error';
      }
      window.setTimeout(() => {
        button.textContent = original;
        delete button.dataset.state;
        button.setAttribute('aria-label', `Скопировать ${command}`);
      }, 1600);
    });
  });
})();
