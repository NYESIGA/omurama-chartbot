(function () {
  const baseUrl = window.OMURAMA_CHATBOT_URL || window.location.origin;
  const apiKey = window.OMURAMA_CHATBOT_API_KEY || "";
  if (!baseUrl) {
    console.warn("Omurama chatbot: OMURAMA_CHATBOT_URL is required.");
    return;
  }

  const sanitize = (value) => String(value || "");

  const createElement = (tag, attrs = {}, ...children) => {
    const el = document.createElement(tag);
    Object.entries(attrs).forEach(([key, value]) => {
      if (key === "className") el.className = value;
      else if (key === "innerHTML") el.innerHTML = value;
      else el.setAttribute(key, value);
    });
    children.forEach((child) => {
      if (typeof child === "string") child = document.createTextNode(child);
      if (child) el.appendChild(child);
    });
    return el;
  };

  const stylesheetId = "omurama-widget-style";
  if (!document.getElementById(stylesheetId)) {
    const link = createElement("link", {
      id: stylesheetId,
      rel: "stylesheet",
      href: `${baseUrl}/widget.css`,
    });
    document.head.appendChild(link);
  }

  const container = createElement("div", { className: "omurama-widget" });
  const card = createElement("div", { className: "omurama-card" });
  const header = createElement(
    "div",
    { className: "omurama-header" },
    createElement(
      "div",
      null,
      createElement("p", { className: "omurama-title" }, "Omurama AI Assistant"),
      createElement("p", { className: "omurama-subtitle" }, "Chat, image, voice, file upload")
    ),
    createElement(
      "button",
      { className: "omurama-button secondary", type: "button" },
      "Close"
    )
  );

  const messages = createElement("div", { className: "omurama-messages" });
  const controls = createElement("div", { className: "omurama-controls" });
  const inputRow = createElement("div", { className: "omurama-input-row" });
  const messageInput = createElement("textarea", {
    className: "omurama-input",
    placeholder: "Ask anything...",
    rows: "2",
  });
  const sendButton = createElement(
    "button",
    { className: "omurama-button", type: "button" },
    "Send"
  );
  const actions = createElement("div", { className: "omurama-actions" });
  const voiceButton = createElement(
    "button",
    { className: "omurama-action", type: "button" },
    "Voice"
  );
  const imageButton = createElement(
    "button",
    { className: "omurama-action", type: "button" },
    "Image"
  );
  const fileInput = createElement("input", {
    type: "file",
    accept: "image/*,audio/*,*/*",
    style: "display:none;",
  });
  const status = createElement("p", { className: "omurama-status" }, "Ready.");

  inputRow.append(messageInput, sendButton);
  actions.append(voiceButton, imageButton);
  controls.append(inputRow, actions, fileInput, status);
  card.append(header, createElement("div", { className: "omurama-body" }, messages, controls));
  container.appendChild(card);
  document.body.appendChild(container);

  const apiHeaders = {
    "Accept": "application/json",
    "x-api-key": apiKey,
  };

  const appendMessage = (text, role) => {
    if (!text) return;
    const bubble = createElement("div", { className: `omurama-message ${role}` }, sanitize(text));
    messages.appendChild(bubble);
    messages.scrollTop = messages.scrollHeight;
  };

  const fetchApi = async (path, options) => {
    status.textContent = "Processing...";
    try {
      const response = await fetch(`${baseUrl}${path}`, options);
      if (!response.ok) {
        const error = await response.text();
        throw new Error(error || response.statusText);
      }
      const data = await response.json();
      status.textContent = "Ready.";
      return data;
    } catch (error) {
      status.textContent = `Error: ${error.message}`;
      console.error(error);
      return null;
    }
  };

  const sendChat = async (text) => {
    if (!text.trim()) return;
    appendMessage(text, "user");
    messageInput.value = "";
    const payload = { messages: [{ role: "user", content: text }] };
    const result = await fetchApi("/chat", {
      method: "POST",
      headers: { ...apiHeaders, "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (result && result.answer) {
      appendMessage(result.answer, "assistant");
      if (result.answer_audio_base64) {
        playAudio(result.answer_audio_base64, result.content_type || "audio/wav");
      }
    }
  };

  const uploadImage = async (file) => {
    if (!file) return;
    const form = new FormData();
    form.append("image", file);
    form.append("question", "Describe the image and answer questions.");
    const response = await fetchApi("/vision", {
      method: "POST",
      headers: { ...apiHeaders },
      body: form,
    });
    if (response && response.result) {
      appendMessage(`Image result: ${response.result}`, "assistant");
    }
  };

  const recordVoice = async () => {
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      status.textContent = "Voice recording is not supported in this browser.";
      return;
    }

    status.textContent = "Recording... Tap again to stop.";
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const recorder = new MediaRecorder(stream);
    const chunks = [];

    recorder.ondataavailable = (event) => chunks.push(event.data);
    recorder.onstop = async () => {
      stream.getTracks().forEach((track) => track.stop());
      const blob = new Blob(chunks, { type: "audio/webm" });
      const form = new FormData();
      form.append("mode", "transcribe");
      form.append("audio", blob, "voice.webm");
      const response = await fetchApi("/voice", {
        method: "POST",
        headers: { ...apiHeaders },
        body: form,
      });
      if (response && response.transcription) {
        appendMessage(response.transcription, "user");
        sendChat(response.transcription);
      }
    };

    recorder.start();
    voiceButton.textContent = "Stop";
    voiceButton.onclick = () => {
      recorder.stop();
      voiceButton.textContent = "Voice";
      voiceButton.onclick = handleVoice;
    };
  };

  const handleVoice = () => {
    recordVoice();
  };

  const playAudio = (base64, contentType) => {
    try {
      const bytes = atob(base64);
      const buffer = new Uint8Array(bytes.length);
      for (let i = 0; i < bytes.length; i += 1) {
        buffer[i] = bytes.charCodeAt(i);
      }
      const blob = new Blob([buffer], { type: contentType });
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.play();
    } catch (error) {
      console.warn("Failed to play audio", error);
    }
  };

  const handleSend = () => {
    const value = messageInput.value;
    if (!value.trim()) return;
    sendChat(value);
  };

  sendButton.addEventListener("click", handleSend);
  messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSend();
    }
  });

  imageButton.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => {
    const file = fileInput.files[0];
    if (file) {
      if (file.type.startsWith("image/")) {
        uploadImage(file);
      } else {
        status.textContent = "Only image uploads are supported by the widget.";
      }
    }
  });

  voiceButton.addEventListener("click", handleVoice);
  header.querySelector("button").addEventListener("click", () => {
    container.style.display = "none";
  });
})();
