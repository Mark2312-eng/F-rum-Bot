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

  // Unified support center: Telegram Login, private ticket history and replies.
  const supportApi = 'https://f-rum-bot.onrender.com/api/support';
  const supportAuth = document.getElementById('supportAuth');
  const supportWorkspace = document.getElementById('supportWorkspace');
  const supportTickets = document.getElementById('supportTickets');
  const supportThread = document.getElementById('supportThread');
  const supportFeedback = document.getElementById('supportFeedback');

  const supportRequest = async (path, options = {}) => {
    const response = await fetch(`${supportApi}${path}`, {
      credentials: 'include', ...options,
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || 'Не удалось выполнить запрос.');
    return data;
  };
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[char]);
  const statusLabel = status => ({
    open: 'Открыто', waiting_user: 'Ожидает вашего ответа',
    waiting_support: 'Ожидает поддержки', closed: 'Закрыто'
  })[status] || status;

  const loadSupportTickets = async () => {
    if (!supportTickets) return;
    supportTickets.innerHTML = '<p class="support-empty">Загрузка…</p>';
    try {
      const data = await supportRequest('/tickets');
      if (!data.tickets.length) {
        supportTickets.innerHTML = '<p class="support-empty">Пока нет обращений. Создайте первое слева.</p>';
        return;
      }
      supportTickets.innerHTML = data.tickets.map(ticket => `
        <button class="support-ticket" type="button" data-ticket-id="${ticket.id}">
          <span><b>#${ticket.id} · ${escapeHtml(ticket.subject)}</b><small>${escapeHtml(statusLabel(ticket.status))}</small></span>
          <span class="support-ticket-arrow">›</span>
        </button>`).join('');
      supportTickets.querySelectorAll('[data-ticket-id]').forEach(button =>
        button.addEventListener('click', () => openSupportThread(button.dataset.ticketId)));
    } catch (error) { supportTickets.innerHTML = `<p class="support-empty">${escapeHtml(error.message)}</p>`; }
  };

  const openSupportThread = async id => {
    try {
      const data = await supportRequest(`/tickets/${id}`);
      supportThread.hidden = false;
      supportThread.innerHTML = `
        <div class="support-thread-head"><div><b>Обращение #${data.ticket.id}</b><small>${escapeHtml(statusLabel(data.ticket.status))}</small></div><button type="button" id="supportThreadClose" aria-label="Закрыть переписку">×</button></div>
        <div class="support-messages">${data.messages.map(message => `
          <article class="support-message ${message.author_role === 'staff' ? 'is-staff' : 'is-user'}">
            <small>${message.author_role === 'staff' ? 'Поддержка' : 'Вы'} · ${new Date(message.created_at).toLocaleString('ru-RU')}</small>
            <p>${escapeHtml(message.body)}</p>
          </article>`).join('')}</div>
        ${data.ticket.status === 'closed' ? '<p class="support-closed-note">Обращение закрыто. Создайте новое, если нужна дополнительная помощь.</p>' : `
          <form id="supportReplyForm" class="support-reply-form">
            <textarea name="message" maxlength="2000" rows="3" required placeholder="Напишите ответ…"></textarea>
            <button class="button button-primary" type="submit">Отправить ответ</button>
          </form>`}
      `;
      document.getElementById('supportThreadClose')?.addEventListener('click', () => { supportThread.hidden = true; });
      document.getElementById('supportReplyForm')?.addEventListener('submit', async event => {
        event.preventDefault();
        const form = event.currentTarget;
        const message = new FormData(form).get('message').toString().trim();
        if (!message) return;
        const button = form.querySelector('button');
        button.disabled = true;
        try {
          await supportRequest(`/tickets/${id}/messages`, { method: 'POST', body: JSON.stringify({ message }) });
          await openSupportThread(id);
          await loadSupportTickets();
        } catch (error) { supportFeedback.textContent = error.message; button.disabled = false; }
      });
    } catch (error) { supportFeedback.textContent = error.message; }
  };

  const showSupportWorkspace = async user => {
    supportAuth.hidden = true;
    supportWorkspace.hidden = false;
    document.getElementById('supportWelcome').textContent = user?.first_name ? `Здравствуйте, ${user.first_name}` : 'Вы вошли через Telegram';
    await loadSupportTickets();
  };

  window.onTelegramAuth = async user => {
    try {
      await supportRequest('/auth/telegram', { method: 'POST', body: JSON.stringify(user) });
      await showSupportWorkspace(user);
    } catch (error) {
      const hint = document.querySelector('.support-hint');
      if (hint) hint.textContent = error.message;
    }
  };

  const mountTelegramLogin = async () => {
    const host = document.getElementById('telegramLoginWidget');
    host.innerHTML = '<button class="button button-primary support-login-button" type="button">Войти через Telegram <span>↗</span></button>';
    host.querySelector('button').addEventListener('click', () => {
      const popup = window.open(
        'https://f-rum-bot-panel.onrender.com/support-login.html',
        'fRumTelegramLogin',
        'width=520,height=620,resizable=yes,scrollbars=yes'
      );
      if (!popup) {
        const hint = document.querySelector('.support-hint');
        if (hint) hint.textContent = 'Браузер заблокировал окно входа. Разрешите всплывающие окна для сайта и повторите попытку.';
      }
    });
  };

  window.addEventListener('message', event => {
    if (event.origin !== 'https://f-rum-bot-panel.onrender.com' ||
        event.data?.type !== 'f-rum-support-auth' ||
        !event.data.user) return;
    window.onTelegramAuth(event.data.user);
  });

  if (supportAuth) {
    supportRequest('/me').then(async data => {
      if (data.authenticated) await showSupportWorkspace({ first_name: 'пользователь' });
      else await mountTelegramLogin();
    }).catch(() => {
      const hint = document.querySelector('.support-hint');
      if (hint) hint.textContent = 'Не удалось подключиться к поддержке. Попробуйте обновить страницу.';
    });
  }

  document.getElementById('supportCreateForm')?.addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const subject = form.elements.subject.value.trim();
    const message = form.elements.message.value.trim();
    const button = form.querySelector('button[type="submit"]');
    if (!subject || !message) return;
    button.disabled = true;
    supportFeedback.textContent = 'Отправляем обращение…';
    try {
      const data = await supportRequest('/tickets', { method: 'POST', body: JSON.stringify({ subject, message }) });
      form.reset();
      supportFeedback.textContent = `Обращение #${data.ticket_id} создано.`;
      await loadSupportTickets();
      await openSupportThread(data.ticket_id);
    } catch (error) { supportFeedback.textContent = error.message; }
    finally { button.disabled = false; }
  });
  document.getElementById('supportRefresh')?.addEventListener('click', loadSupportTickets);
  document.getElementById('supportLogout')?.addEventListener('click', async () => {
    try { await supportRequest('/logout', { method: 'POST' }); } catch {}
    supportWorkspace.hidden = true;
    supportAuth.hidden = false;
    supportThread.hidden = true;
    document.getElementById('telegramLoginWidget').innerHTML = '';
    await mountTelegramLogin().catch(() => {});
  });

})();
