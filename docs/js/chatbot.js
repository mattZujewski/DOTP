/**
 * chatbot.js — Floating LLM chatbot (Anthropic API, direct from browser)
 * - Model: claude-haiku-4-5 (fast, cheap)
 * - API key stored in localStorage('dotp_apikey')
 * - Streaming via fetch() + ReadableStream
 * - Builds system prompt from pre-loaded JSON data
 * - Auto-injected on all pages
 */

(function () {
  'use strict';

  const STORAGE_KEY  = 'dotp_apikey';
  const MODEL        = 'claude-haiku-4-5';
  const MAX_HISTORY  = 10; // message pairs kept in session

  let conversationHistory = [];
  let systemPrompt = '';
  let isStreaming  = false;

  // ── Suggested prompts (vary by page) ─────────────────────────────
  function getSuggestedPrompts() {
    const path = window.location.pathname;
    if (path.includes('trade')) return [
      'Who has made the most trades?',
      'Who trades with each other the most?',
      'Have there been any 3-team trades?',
    ];
    if (path.includes('player_history')) return [
      'Which player has been on the most teams?',
      'Who has had the most roster turnover?',
      'How long do players typically stay on a roster?',
    ];
    if (path.includes('team')) return [
      'What is this owner\'s trade history?',
      'Who is their best player?',
      'How many seasons have they played?',
    ];
    return [
      'Who is the best trader in the league?',
      'What is the most traveled player?',
      'Give me a league summary.',
    ];
  }

  // ── Build system prompt from loaded data ──────────────────────────
  async function buildSystemPrompt() {
    try {
      const D = window.DOTP;
      if (!D) return 'You are a helpful fantasy baseball dynasty league assistant.';

      const [teams, trades, journeys] = await Promise.all([
        D.loadJSON('data/teams.json').catch(()=>null),
        D.loadJSON('data/trades.json').catch(()=>null),
        D.loadJSON('data/journeys.json').catch(()=>null),
      ]);

      const meta = teams?.meta || {};
      const owners = teams?.owners || [];

      const ownerLines = owners.map(o => {
        const s = o.stats || {};
        return `- ${o.real_name} (${o.current_team}): ${s.total_trades||0} trades, ${s.unique_players_rostered||0} unique players, fav acquisition: ${s.most_common_acquisition||'?'}, top partner: ${s.most_traded_with||'?'}`;
      }).join('\n');

      const topTrades = (trades?.trade_pairs||[]).slice(0,5).map(p =>
        `  ${p.party_a} ↔ ${p.party_b}: ${p.count} trades`
      ).join('\n');

      const topTravelers = (journeys?.most_traveled_players||[]).slice(0,5).map(p =>
        `  ${p.player_name}: ${p.distinct_teams} teams, ${p.total_stints} stints`
      ).join('\n');

      const tenureStats = journeys?.tenure_stats || {};

      return `You are a knowledgeable assistant for the "Ducks on the Pond Dynasty" fantasy baseball league.

## League Summary
- League: ${meta.league_name || 'Ducks on the Pond Dynasty'}
- Seasons: ${(meta.seasons||[]).join(', ')}
- Total trade events: ${meta.total_trade_events || '?'}
- Total unique players ever rostered: ${meta.total_unique_players || '?'}
- Total owners: ${meta.total_owners || 12}

## Owners & Current Teams
${ownerLines}

## Top Trade Pairs (all-time)
${topTrades || '  (none)'}

## Most Traveled Players
${topTravelers || '  (none)'}

## Tenure Stats
- Median player tenure: ${Math.round(tenureStats.median_days||0)} days
- Mean player tenure: ${Math.round(tenureStats.mean_days||0)} days

## Your Role
Answer questions about this dynasty league. Be specific with numbers. If asked about a player or trade you don't have data on, say so honestly. Keep answers concise and conversational. You have data on 6 seasons (2021–2026).`;

    } catch (e) {
      return `You are a helpful assistant for the Ducks on the Pond Dynasty fantasy baseball league (6 seasons, 12 owners). Answer questions about trades, players, and owners.`;
    }
  }

  // ── Inject chatbot UI ─────────────────────────────────────────────
  function injectUI() {
    const suggestions = getSuggestedPrompts();

    document.body.insertAdjacentHTML('beforeend', `
      <button id="chatbot-fab" aria-label="Open league chatbot" title="Ask the league bot">💬</button>

      <div id="chatbot-panel" role="dialog" aria-label="League Chatbot">
        <div class="chatbot-header">
          <span style="font-size:1.1rem">🦆</span>
          <div style="flex:1">
            <div class="chatbot-header-title">League Assistant</div>
            <div class="chatbot-header-sub">Powered by Claude · asks use your API key</div>
          </div>
          <button class="chatbot-close-btn" id="chatbot-close" aria-label="Close chatbot">×</button>
        </div>
        <div class="chatbot-messages" id="chatbot-messages">
          <div class="chatbot-msg assistant">
            Hey! I know everything about the Ducks on the Pond Dynasty league. Ask me about trades, players, owners, or anything else! 🦆
          </div>
        </div>
        <div class="chatbot-suggestions" id="chatbot-suggestions">
          ${suggestions.map(s=>`<button class="chatbot-suggestion-btn">${s}</button>`).join('')}
        </div>
        <div class="chatbot-input-row">
          <textarea class="chatbot-input" id="chatbot-input" rows="1" placeholder="Ask about the league…" aria-label="Chat message"></textarea>
          <button class="chatbot-send-btn" id="chatbot-send" aria-label="Send">↑</button>
        </div>
      </div>
    `);

    const fab       = document.getElementById('chatbot-fab');
    const panel     = document.getElementById('chatbot-panel');
    const closeBtn  = document.getElementById('chatbot-close');
    const input     = document.getElementById('chatbot-input');
    const sendBtn   = document.getElementById('chatbot-send');
    const msgArea   = document.getElementById('chatbot-messages');
    const sugArea   = document.getElementById('chatbot-suggestions');

    // Toggle panel
    fab.addEventListener('click', () => {
      panel.classList.toggle('open');
      if (panel.classList.contains('open')) {
        input.focus();
        sugArea.style.display = conversationHistory.length > 0 ? 'none' : '';
      }
    });
    closeBtn.addEventListener('click', () => panel.classList.remove('open'));

    // Suggestion buttons
    sugArea.addEventListener('click', e => {
      const btn = e.target.closest('.chatbot-suggestion-btn');
      if (!btn) return;
      input.value = btn.textContent;
      sugArea.style.display = 'none';
      sendMessage();
    });

    // Send on Enter (Shift+Enter for newline)
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });
    sendBtn.addEventListener('click', sendMessage);

    // Auto-resize textarea
    input.addEventListener('input', () => {
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 80) + 'px';
    });

    async function sendMessage() {
      const text = input.value.trim();
      if (!text || isStreaming) return;

      // Get API key
      let apiKey = localStorage.getItem(STORAGE_KEY);
      if (!apiKey) {
        apiKey = prompt('Enter your Anthropic API key (stored locally, never sent elsewhere):\n\nGet one at: console.anthropic.com');
        if (!apiKey) return;
        localStorage.setItem(STORAGE_KEY, apiKey.trim());
        apiKey = apiKey.trim();
      }

      // Build system prompt once
      if (!systemPrompt) {
        appendMsg('assistant', '⏳ Loading league data for context…');
        systemPrompt = await buildSystemPrompt();
        // Remove loading msg
        msgArea.lastChild?.remove();
      }

      // Show user message
      input.value = '';
      input.style.height = 'auto';
      appendMsg('user', text);
      sugArea.style.display = 'none';

      // Trim history
      if (conversationHistory.length >= MAX_HISTORY * 2) {
        conversationHistory = conversationHistory.slice(-MAX_HISTORY * 2);
      }
      conversationHistory.push({ role: 'user', content: text });

      // Create assistant bubble
      const assistantBubble = document.createElement('div');
      assistantBubble.className = 'chatbot-msg assistant typing';
      assistantBubble.textContent = '…';
      msgArea.appendChild(assistantBubble);
      scrollToBottom();

      isStreaming = true;
      sendBtn.disabled = true;

      let fullResponse = '';

      try {
        const response = await fetch('https://api.anthropic.com/v1/messages', {
          method: 'POST',
          headers: {
            'x-api-key':                          apiKey,
            'anthropic-version':                  '2023-06-01',
            'anthropic-dangerous-direct-browser-access': 'true',
            'content-type':                       'application/json',
          },
          body: JSON.stringify({
            model:      MODEL,
            max_tokens: 1024,
            stream:     true,
            system:     systemPrompt,
            messages:   conversationHistory,
          }),
        });

        if (!response.ok) {
          const err = await response.json().catch(()=>({error:{message:response.statusText}}));
          const msg = err?.error?.message || response.statusText;
          if (response.status === 401) {
            localStorage.removeItem(STORAGE_KEY);
            throw new Error('Invalid API key — removed. Please try again with a valid key.');
          }
          throw new Error(`API error ${response.status}: ${msg}`);
        }

        // Stream SSE
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const data = line.slice(6);
            if (data === '[DONE]') continue;
            try {
              const parsed = JSON.parse(data);
              if (parsed.type === 'content_block_delta' && parsed.delta?.type === 'text_delta') {
                fullResponse += parsed.delta.text;
                assistantBubble.classList.remove('typing');
                assistantBubble.textContent = fullResponse;
                scrollToBottom();
              }
            } catch (_) {}
          }
        }

        if (!fullResponse) fullResponse = '(No response received)';
        assistantBubble.textContent = fullResponse;
        conversationHistory.push({ role: 'assistant', content: fullResponse });

      } catch (err) {
        assistantBubble.classList.add('typing');
        assistantBubble.textContent = `⚠ ${err.message}`;
        conversationHistory.pop(); // remove the user message that failed
      } finally {
        isStreaming   = false;
        sendBtn.disabled = false;
        input.focus();
        scrollToBottom();
      }
    }

    function appendMsg(role, text) {
      const div = document.createElement('div');
      div.className = `chatbot-msg ${role}`;
      div.textContent = text;
      msgArea.appendChild(div);
      scrollToBottom();
    }

    function scrollToBottom() {
      msgArea.scrollTop = msgArea.scrollHeight;
    }

    // Clear key shortcut (for debugging)
    window.dotpChatClearKey = () => {
      localStorage.removeItem(STORAGE_KEY);
      conversationHistory = [];
      alert('API key and history cleared.');
    };
  }

  // ── Init ──────────────────────────────────────────────────────────
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectUI);
  } else {
    injectUI();
  }

})();
