const chatContainer = document.getElementById('chatContainer');
const chatForm = document.getElementById('chatForm');
const messageInput = document.getElementById('messageInput');
const sendButton = document.getElementById('sendButton');
const agentStatus = document.getElementById('agentStatus');

let isProcessing = false;
let currentMessageElement = null;
let currentSessionId = localStorage.getItem('session_id') || null;

// Function to start a new conversation
function startNewConversation() {
    currentSessionId = null;
    localStorage.removeItem('session_id');
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
    messageContent.innerHTML = formatMessage(content);

    messageDiv.appendChild(avatar);
    messageDiv.appendChild(messageContent);
    chatContainer.appendChild(messageDiv);

    scrollToBottom();
    return messageContent;
}

// Format message with markdown-like formatting
function formatMessage(text) {
    // Convert **bold** to <strong>
    text = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

    // Convert bullet points
    text = text.replace(/^\*   /gm, '• ');

    // Convert line breaks
    text = text.replace(/\n/g, '<br>');

    return text;
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
    
    const agentLabel = agentName ? `<div class="agent-label">${agentName} is thinking...</div>` : '';
    
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
            const agentLabel = `<div class="agent-label">${agentName} is thinking...</div>`;
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
        statusText.textContent = `${agentName} is thinking...`;
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

    // Add user message
    addMessage(userMessage, true);

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
                    } else if (data.type === 'stream') {
                        removeTypingIndicator();
                        if (!currentMessageElement) {
                            currentMessageElement = addMessage('');
                        }
                        currentMessageElement.innerHTML += data.content;
                        scrollToBottom();
                    } else if (data.type === 'final') {
                        removeTypingIndicator();
                        if (!currentMessageElement) {
                            addMessage(data.content);
                        }
                        currentMessageElement = null;
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
                    } else if (data.type === 'done') {
                        updateAgentStatus(null);
                        isProcessing = false;
                        sendButton.disabled = false;
                        messageInput.disabled = false;
                        messageInput.focus();
                    } else if (data.type === 'error') {
                        removeTypingIndicator();
                        addMessage(`Error: ${data.message}`);
                        updateAgentStatus(null);
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
