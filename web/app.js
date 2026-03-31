document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('config-form');
    const runBtn = document.getElementById('run-btn');
    const btnText = document.getElementById('btn-text');
    const btnSpinner = document.getElementById('btn-spinner');
    const terminalWindow = document.getElementById('terminal-window');
    
    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');

    const resultsContainer = document.getElementById('results-container');
    const resultsEmpty = document.getElementById('results-empty');
    const linksGrid = document.getElementById('links-grid');
    const articlePreview = document.getElementById('article-preview');

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        // 1. Prepare UI
        runBtn.disabled = true;
        btnText.style.display = 'none';
        btnSpinner.style.display = 'block';
        
        statusDot.className = 'dot running';
        statusText.textContent = 'Agent Swarm Active';
        
        terminalWindow.innerHTML = '<div class="log-line system-text">🚀 Initialization Sequence Started...</div>';
        
        resultsContainer.style.display = 'none';
        resultsEmpty.style.display = 'flex';
        resultsEmpty.innerHTML = '<span>Swarm is working. Results will appear here when complete.</span>';
        linksGrid.innerHTML = '';
        articlePreview.innerHTML = '';

        // 2. Gather Data
        const payload = {
            topics: document.getElementById('topics').value,
            timeframe: document.getElementById('timeframe').value,
            target_stories: document.getElementById('stories').value,
            post_x: document.getElementById('post_x').checked,
            post_linkedin: document.getElementById('post_linkedin').checked,
            post_blog: document.getElementById('post_blog').checked,
        };

        // 3. Connect to API stream (SSE over POST via fetch)
        try {
            const response = await fetch('/api/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (!response.body) throw new Error('ReadableStream not yet supported in this browser.');
            
            const reader = response.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let buffer = '';

            let isDone = false;

            let currentEvent = 'message';
            while (!isDone) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                
                // Keep the last incomplete line in the buffer
                buffer = lines.pop();

                for (let line of lines) {
                    line = line.trim();
                    if (!line) continue;

                    if (line.startsWith('event:')) {
                        currentEvent = line.substring(6).trim();
                    } else if (line.startsWith('data:')) {
                        const dataStr = line.substring(5).trim();
                        try {
                            const dataObj = JSON.parse(dataStr);
                            handleStreamEvent(currentEvent, dataObj);
                            currentEvent = 'message'; // reset after handling
                        } catch (e) {
                            console.error('JSON parse error from stream line:', dataStr);
                        }
                    }
                }
            }

        } catch (error) {
            appendLog('❌ CRITICAL ERROR: ' + error.message, true);
            statusDot.className = 'dot error';
            statusText.textContent = 'Connection Failed';
        } finally {
            runBtn.disabled = false;
            btnText.style.display = 'block';
            btnSpinner.style.display = 'none';
            if (statusDot.className.includes('running')) {
                statusDot.className = 'dot';
                statusText.textContent = 'Completed';
            }
        }
    });

    function handleStreamEvent(event, data) {
        if (event === 'log') {
            appendLog(data.message);
        } else if (event === 'done') {
            appendLog('✅ Pipeline execution finished successfully.', false, true);
            statusDot.className = 'dot';
            statusText.textContent = 'Completed';
            renderResults(data);
        } else if (event === 'error') {
            appendLog('❌ Pipeline Error: ' + data.error, true);
            statusDot.className = 'dot error';
            statusText.textContent = 'Agent Failed';
        }
    }

    function appendLog(text, isError = false, isSystem = false) {
        const div = document.createElement('div');
        div.className = 'log-line';
        if (isError) div.classList.add('error-text');
        if (isSystem) div.classList.add('system-text');
        
        div.textContent = text;
        terminalWindow.appendChild(div);
        
        // Auto-scroll
        terminalWindow.scrollTop = terminalWindow.scrollHeight;
    }

    function renderResults(state) {
        resultsEmpty.style.display = 'none';
        resultsContainer.style.display = 'block';

        const { published_urls, full_blog_post, x_thread_full, linkedin_post } = state;

        // 1. Render Links
        if (published_urls && Object.keys(published_urls).length > 0) {
            // Mapping internal keys to display names and icons
            const urlConfig = {
                'blog': { name: 'Hashnode Blog', icon: '📝' },
                'x': { name: 'X / Twitter', icon: '🐦' },
                'linkedin': { name: 'LinkedIn', icon: '💼' }
            };

            for (const [key, url] of Object.entries(published_urls)) {
                if (!url) continue;
                
                const meta = urlConfig[key] || { name: key.toUpperCase(), icon: '🔗' };
                
                const card = document.createElement('a');
                card.className = 'link-card block';
                card.href = url.startsWith('http') ? url : 'https://' + url;
                card.target = '_blank';
                card.innerHTML = `
                    <div class="card-title">
                        ${meta.name} <span>${meta.icon}</span>
                    </div>
                    <div class="card-url text-muted">${url}</div>
                `;
                linksGrid.appendChild(card);
            }
        }

        // 2. Render Article Preview
        let previewMarkdown = '';
        
        if (full_blog_post) {
            previewMarkdown += full_blog_post;
        }

        if (x_thread_full && x_thread_full.length > 0) {
            previewMarkdown += '\\n\\n---\\n\\n## 🐦 X/Twitter Thread Preview\\n\\n';
            x_thread_full.forEach((tweet, i) => {
                previewMarkdown += `**Tweet ${i + 1}**\\n> ${tweet.split('\\n').join('\\n> ')}\\n\\n`;
            });
        }

        if (linkedin_post) {
            previewMarkdown += '\\n\\n---\\n\\n## 💼 LinkedIn Post Preview\\n\\n';
            previewMarkdown += `> ${linkedin_post.split('\\n').join('\\n> ')}`;
        }

        if (previewMarkdown) {
            if (window.marked && typeof marked.parse === 'function') {
                articlePreview.innerHTML = marked.parse(previewMarkdown);
            } else {
                articlePreview.innerHTML = '<pre style="white-space: pre-wrap; font-family: inherit;">' + previewMarkdown + '</pre>';
            }
        } else {
            articlePreview.innerHTML = '<p class="text-muted">No content to preview.</p>';
        }
    }
});
