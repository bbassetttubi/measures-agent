const chatContainer = document.getElementById('chatContainer');
const chatForm = document.getElementById('chatForm');
const messageInput = document.getElementById('messageInput');
const sendButton = document.getElementById('sendButton');
const agentStatus = document.getElementById('agentStatus');
const focusPill = document.getElementById('focusPill');

let isProcessing = false;
let currentMessageElement = null;
let currentMessageMarkdown = '';
let currentAgentName = null;
let hasStreamContent = false;
let currentSessionId = localStorage.getItem('session_id') || null;
let renderedWidgets = new Set();  // Track which widgets we've already rendered to prevent duplicates
let lastFocus = null;

// Function to start a new conversation
function startNewConversation() {
    currentSessionId = null;
    localStorage.removeItem('session_id');
    renderedWidgets.clear();  // Clear widget tracking for new conversation
    chatContainer.innerHTML = `
        <div class="welcome-message">
            <div class="welcome-icon">👋</div>
            <h2>Welcome to your AI Health Assistant</h2>
            <p>Ask me about your health, biomarkers, exercise, nutrition, or any wellness questions.</p>
            <div class="example-queries">
                <button class="example-btn" onclick="sendExample('What are my biggest health issues?')">
                    What are my biggest health issues?
                </button>
                <button class="example-btn" onclick="sendExample('How do I lower my cholesterol?')">
                    How do I lower my cholesterol?
                </button>
                <button class="example-btn" onclick="sendExample('What exercises would you recommend?')">
                    What exercises would you recommend?
                </button>
            </div>
        </div>
    `;
    updateFocusPill(null);
    messageInput.focus();
}

// Send example query
function sendExample(message) {
    messageInput.value = message;
    chatForm.dispatchEvent(new Event('submit'));
}

// Add message to chat
function addMessage(content, isUser = false) {
    // Remove welcome message if it exists
    const welcomeMsg = chatContainer.querySelector('.welcome-message');
    if (welcomeMsg) {
        welcomeMsg.remove();
    }

    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${isUser ? 'user' : 'assistant'}`;

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = isUser ? '👤' : '🤖';

    const messageContent = document.createElement('div');
    messageContent.className = 'message-content';
    messageContent.innerHTML = renderMarkdown(content);

    messageDiv.appendChild(avatar);
    messageDiv.appendChild(messageContent);
    chatContainer.appendChild(messageDiv);

    scrollToBottom();
    return messageContent;
}

// Add widget to last message
function addWidget(widgetType, widgetData) {
    // Create unique widget ID to prevent duplicates
    const widgetId = `${widgetType}:${JSON.stringify(widgetData)}`;
    
    // Check if we've already rendered this exact widget
    if (renderedWidgets.has(widgetId)) {
        console.log('Skipping duplicate widget:', widgetType);
        return;
    }
    
    // Mark as rendered
    renderedWidgets.add(widgetId);
    
    // Find the last assistant message or create one if needed
    let lastMessage = chatContainer.querySelector('.message.assistant:last-child .message-content');
    
    if (!lastMessage) {
        lastMessage = addMessage('');
    }
    
    // Create widget container
    const widgetDiv = document.createElement('div');
    widgetDiv.className = 'chat-widget';
    
    // Render widget based on type
    if (widgetType === 'Workout plan') {
        widgetDiv.innerHTML = renderWorkoutWidget(widgetData);
    } else if (widgetType === 'Meal plan: watch & order') {
        widgetDiv.innerHTML = renderMealPlanWidget(widgetData);
    } else if (widgetType === 'Supplements — Thorne') {
        widgetDiv.innerHTML = renderSupplementWidget(widgetData);
    } else {
        // Generic widget rendering
        widgetDiv.innerHTML = `<pre>${JSON.stringify(widgetData, null, 2)}</pre>`;
    }
    
    lastMessage.appendChild(widgetDiv);
    scrollToBottom();
}

// Render workout plan widget
function renderWorkoutWidget(data) {
    const videos = data.videos.map(video => `
        <div class="widget-list-item">
            <div class="widget-icon">▶️</div>
            <div class="widget-item-content">
                <div class="widget-item-title">${video.title}</div>
                <div class="widget-item-caption">${video.duration} • ${video.focus}</div>
            </div>
            <button class="widget-btn widget-btn-outline" onclick="alert('Video player coming soon!')">Watch</button>
        </div>
    `).join('');
    
    return `
        <div class="widget-card">
            <div class="widget-header">
                <div class="widget-caption">${data.level} • ${data.duration}</div>
                <div class="widget-title">${data.title}</div>
                <div class="widget-description">${data.description}</div>
            </div>
            <div class="widget-divider"></div>
            <div class="widget-list">
                ${videos}
            </div>
            <div class="widget-divider"></div>
            <div class="widget-footer">
                <button class="widget-btn widget-btn-primary" onclick="alert('Starting plan...')">Start plan</button>
                <button class="widget-btn widget-btn-outline" onclick="alert('Shuffling exercises...')">Swap moves</button>
            </div>
        </div>
    `;
}

// Render meal plan widget
function renderMealPlanWidget(data) {
    const meals = data.meals.map(meal => `
        <div class="widget-list-item">
            <div class="widget-badge widget-badge-${meal.mealType.toLowerCase()}">${meal.mealType}</div>
            <div class="widget-item-content">
                <div class="widget-item-title">${meal.title}</div>
            </div>
            <div class="widget-actions">
                <button class="widget-btn widget-btn-sm widget-btn-outline" onclick="window.open('${meal.videoUrl}', '_blank')">
                    ▶️ Watch
                </button>
                <button class="widget-btn widget-btn-sm widget-btn-primary" onclick="window.open('${meal.instacartUrl}', '_blank')">
                    🛒 Order
                </button>
            </div>
        </div>
    `).join('');
    
    return `
        <div class="widget-card">
            <div class="widget-header">
                <div class="widget-title">${data.title}</div>
                <div class="widget-caption">${data.dateLabel}</div>
            </div>
            <div class="widget-divider"></div>
            <div class="widget-list">
                ${meals}
            </div>
        </div>
    `;
}

// Render supplement widget
function renderSupplementWidget(data) {
    const items = data.items.map(item => `
        <div class="widget-list-item">
            <div class="widget-item-content">
                <div class="widget-item-title">${item.name}</div>
                <div class="widget-item-caption">${item.tagline}</div>
            </div>
            <button class="widget-btn widget-btn-sm widget-btn-outline" onclick="window.open('${item.buyUrl}', '_blank')">
                Buy on Thorne →
            </button>
        </div>
    `).join('');
    
    return `
        <div class="widget-card">
            <div class="widget-status">
                <span class="widget-status-icon">🔗</span>
                <span class="widget-status-text">Thorne purchase links</span>
            </div>
            <div class="widget-header">
                <div class="widget-title">${data.title}</div>
                <div class="widget-note">${data.note}</div>
            </div>
            <div class="widget-divider"></div>
            <div class="widget-list">
                ${items}
            </div>
        </div>
    `;
}

// Render markdown safely (fallback to basic formatting if marked isn't available)
function renderMarkdown(text = '') {
    if (window.marked) {
        if (!renderMarkdown.initialized && marked.setOptions) {
            marked.setOptions({ breaks: true, gfm: true });
            renderMarkdown.initialized = true;
        }
        return marked.parse(text);
    }

    // Fallback: lightweight formatting
    let formatted = text
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/^\* /gm, '• ')
        .replace(/\n/g, '<br>');
    return formatted;
}
renderMarkdown.initialized = false;

const agentStatusMessages = {
    "Guardrail": "I'm reviewing your question...",
    "Triage Agent": "I'm coordinating the right specialists...",
    "Physician": "I'm reviewing your biomarkers...",
    "Nutritionist": "I'm analyzing your nutrition data...",
    "Fitness Coach": "I'm crafting your exercise recommendations...",
    "Sleep Doctor": "I'm evaluating your sleep patterns...",
    "Mindfulness Coach": "I'm preparing mindfulness guidance...",
    "User Persona": "I'm checking your preferences...",
    "Critic": "I'm assembling your complete plan...",
    "default": "I'm analyzing your health data..."
};

const focusLabels = {
    "diagnosis": "Diagnosis",
    "plan": "Action Plan",
    "wellbeing": "Wellbeing",
    "progress": "Progress Outlook",
    "acceleration": "Acceleration"
};

function getAgentStatusMessage(agentName) {
    if (!agentName || !agentStatusMessages[agentName]) {
        return agentStatusMessages["default"];
    }
    return agentStatusMessages[agentName];
}

function updateFocusPill(focus) {
    if (!focusPill) return;
    if (!focus) {
        focusPill.classList.add('hidden');
        focusPill.dataset.focus = '';
        lastFocus = null;
        return;
    }
    if (focus === lastFocus) {
        return;
    }
    lastFocus = focus;
    const label = focusLabels[focus] || focus;
    const valueEl = focusPill.querySelector('.pill-value');
    if (valueEl) {
        valueEl.textContent = label;
    }
    focusPill.dataset.focus = focus;
    focusPill.classList.remove('hidden');
}

// Add typing indicator with optional agent name
function addTypingIndicator(agentName = null) {
    const typingDiv = document.createElement('div');
    typingDiv.className = 'message assistant';
    typingDiv.id = 'typingIndicator';

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = '🤖';

    const typingContent = document.createElement('div');
    typingContent.className = 'message-content';
    
    const agentLabelText = agentName ? getAgentStatusMessage(agentName) : agentStatusMessages["default"];
    const agentLabel = `<div class="agent-label">${agentLabelText}</div>`;
    
    typingContent.innerHTML = `
        ${agentLabel}
        <div class="typing-indicator">
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
        </div>
    `;

    typingDiv.appendChild(avatar);
    typingDiv.appendChild(typingContent);
    chatContainer.appendChild(typingDiv);
    scrollToBottom();
}

// Update typing indicator with agent name
function updateTypingIndicator(agentName) {
    const indicator = document.getElementById('typingIndicator');
    if (indicator) {
        const content = indicator.querySelector('.message-content');
        if (content) {
            const agentLabel = `<div class="agent-label">${getAgentStatusMessage(agentName)}</div>`;
            const typingDots = `
                <div class="typing-indicator">
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                </div>
            `;
            content.innerHTML = agentLabel + typingDots;
        }
    }
}

// Remove typing indicator
function removeTypingIndicator() {
    const indicator = document.getElementById('typingIndicator');
    if (indicator) {
        indicator.remove();
    }
}

// Update agent status
function updateAgentStatus(agentName) {
    const statusText = agentStatus.querySelector('.status-text');
    const statusDot = agentStatus.querySelector('.status-dot');

    if (agentName) {
        statusText.textContent = getAgentStatusMessage(agentName);
        statusDot.style.background = 'var(--accent-primary)';
    } else {
        statusText.textContent = 'Ready';
        statusDot.style.background = 'var(--success)';
    }
}

// Scroll to bottom
function scrollToBottom() {
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

// Handle form submission
chatForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    if (isProcessing || !messageInput.value.trim()) {
        return;
    }

    const userMessage = messageInput.value.trim();
    messageInput.value = '';

    // Reset streaming state for new response turn
    currentMessageElement = null;
    currentMessageMarkdown = '';
    currentAgentName = null;
    hasStreamContent = false;

    // Add user message
    addMessage(userMessage, true);
    
    // Clear rendered widgets for new query
    renderedWidgets.clear();

    // Disable input
    isProcessing = true;
    sendButton.disabled = true;
    messageInput.disabled = true;

    // Add typing indicator
    addTypingIndicator();

    // Use fetch with streaming for SSE
    try {
        const requestBody = { message: userMessage };
        if (currentSessionId) {
            requestBody.session_id = currentSessionId;
        }
        
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(requestBody)
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();

            if (done) break;

            buffer += decoder.decode(value, { stream: true });

            // Process complete SSE messages
            const lines = buffer.split('\n\n');
            buffer = lines.pop(); // Keep incomplete message in buffer

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const data = JSON.parse(line.substring(6));

                    if (data.type === 'agent') {
                        updateAgentStatus(data.name);
                        removeTypingIndicator();
                        addTypingIndicator(data.name);
                        // Start a fresh bubble for the next agent's text
                        if (currentAgentName !== data.name) {
                            currentMessageElement = null;
                            currentMessageMarkdown = '';
                            currentAgentName = data.name;
                            hasStreamContent = false;
                        }
                    } else if (data.type === 'widget') {
                        // Render widget
                        removeTypingIndicator();
                        addWidget(data.widget, data.data);
                    } else if (data.type === 'stream') {
                        removeTypingIndicator();
                        hasStreamContent = true;
                        if (!currentMessageElement) {
                            currentMessageMarkdown = '';
                            currentMessageElement = addMessage('');
                        }
                        currentMessageMarkdown += data.content;
                        currentMessageElement.innerHTML = renderMarkdown(currentMessageMarkdown);
                        scrollToBottom();
                    } else if (data.type === 'final') {
                        removeTypingIndicator();
                        if (data.content) {
                            if (currentMessageElement && !hasStreamContent) {
                                currentMessageMarkdown += data.content;
                                currentMessageElement.innerHTML = renderMarkdown(currentMessageMarkdown);
                            } else if (!currentMessageElement) {
                                currentMessageMarkdown = data.content;
                                addMessage(data.content);
                            }
                        } else if (!currentMessageElement && !hasStreamContent) {
                            addMessage('');
                        }
                        currentMessageElement = null;
                        currentMessageMarkdown = '';
                        hasStreamContent = false;
                        // Store session ID if provided
                        if (data.session_id) {
                            currentSessionId = data.session_id;
                            localStorage.setItem('session_id', data.session_id);
                        }
                    } else if (data.type === 'session') {
                        // Handle session ID update
                        if (data.session_id) {
                            currentSessionId = data.session_id;
                            localStorage.setItem('session_id', data.session_id);
                        }
                    } else if (data.type === 'trace') {
                        console.debug('Agent trace:', data.entries);
                    } else if (data.type === 'status') {
                        updateFocusPill(data.focus);
                    } else if (data.type === 'done') {
                        updateAgentStatus(null);
                        currentAgentName = null;
                        hasStreamContent = false;
                        isProcessing = false;
                        sendButton.disabled = false;
                        messageInput.disabled = false;
                        messageInput.focus();
                    } else if (data.type === 'error') {
                        removeTypingIndicator();
                        addMessage(`Error: ${data.message}`);
                        updateAgentStatus(null);
                        currentAgentName = null;
                        hasStreamContent = false;
                        isProcessing = false;
                        sendButton.disabled = false;
                        messageInput.disabled = false;
                    }
                }
            }
        }
    } catch (error) {
        console.error('Error:', error);
        removeTypingIndicator();
        addMessage('Sorry, there was an error processing your request.');
        updateAgentStatus(null);
        isProcessing = false;
        sendButton.disabled = false;
        messageInput.disabled = false;
    }
});

// Focus input on load
messageInput.focus();
