const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const fileInfo = document.getElementById('file-info');
const fileName = document.getElementById('file-name');
const clearBtn = document.getElementById('clear-btn');
const uploadBtn = document.getElementById('upload-btn');

const uploadSection = document.getElementById('upload-section');
const progressSection = document.getElementById('progress-section');
const errorSection = document.getElementById('error-section');
const doneSection = document.getElementById('done-section');

const progressFill = document.getElementById('progress-fill');
const progressStep = document.getElementById('progress-step');
const progressPct = document.getElementById('progress-pct');
const progressEta = document.getElementById('progress-eta');
const uploadFileInfo = document.getElementById('upload-file-info');
const errorMsg = document.getElementById('error-msg');

let selectedFile = null;
let currentJobId = null;

// ===== Server health check (every 5s) =====
const disconnectBanner = document.getElementById('disconnect-banner');
let serverOnline = true;

setInterval(async () => {
    try {
        const resp = await fetch('/health', { signal: AbortSignal.timeout(3000) });
        if (resp.ok && !serverOnline) {
            serverOnline = true;
            disconnectBanner.hidden = true;
        }
    } catch {
        if (serverOnline) {
            serverOnline = false;
            disconnectBanner.hidden = false;
        }
    }
}, 5000);

// ===== Restore from localStorage on page load =====
// Deferred to end of file so resetUI is available

// ===== File selection =====
dropZone.addEventListener('click', () => fileInput.click());

dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('dragover');
});

dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('dragover');
});

dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    if (e.dataTransfer.files.length) {
        selectFile(e.dataTransfer.files[0]);
    }
});

fileInput.addEventListener('change', () => {
    if (fileInput.files.length) {
        selectFile(fileInput.files[0]);
    }
});

clearBtn.addEventListener('click', () => {
    selectedFile = null;
    fileInfo.hidden = true;
    dropZone.hidden = false;
    uploadBtn.disabled = true;
    fileInput.value = '';
});

function selectFile(file) {
    selectedFile = file;
    fileName.textContent = `${file.name} (${formatSize(file.size)})`;
    fileInfo.hidden = false;
    dropZone.hidden = true;
    uploadBtn.disabled = false;
}

function formatSize(bytes) {
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
}

function formatEta(seconds) {
    if (seconds < 0) return '预估时间计算中...';
    if (seconds < 60) return `预计剩余 ${seconds} 秒`;
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    if (mins < 60) return `预计剩余 ${mins} 分 ${secs} 秒`;
    const hours = Math.floor(mins / 60);
    const remainMins = mins % 60;
    return `预计剩余 ${hours} 小时 ${remainMins} 分`;
}

// ===== Upload =====
uploadBtn.addEventListener('click', async () => {
    if (!selectedFile) return;

    uploadBtn.disabled = true;
    uploadBtn.textContent = '上传中...';

    const lang = document.getElementById('source-lang').value;

    const formData = new FormData();
    formData.append('file', selectedFile);
    formData.append('language', lang);

    try {
        const resp = await fetch('/upload', { method: 'POST', body: formData });
        const data = await resp.json();

        if (data.error) {
            showError(data.error);
            return;
        }

        currentJobId = data.job_id;
        localStorage.setItem('chaossubs_job_id', currentJobId);
        uploadFileInfo.textContent = `视频导入成功 — ${selectedFile.name} (${formatSize(selectedFile.size)})`;
        showSection('progress');
        connectWebSocket(currentJobId);
    } catch (e) {
        showError('上传失败: ' + e.message);
    }
});

// ===== WebSocket progress (Phase 1) =====
function connectWebSocket(jobId) {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${location.host}/ws/${jobId}`);

    ws.onmessage = (event) => {
        const job = JSON.parse(event.data);

        if (job.error && job.status === 'error') {
            showError(job.error);
            return;
        }

        if (job.status === 'done' && !job.burn_status) {
            showSection('done');
            document.getElementById('dl-original-srt').href = `/download/${jobId}/original-srt`;
            document.getElementById('dl-srt').href = `/download/${jobId}/srt`;
            document.getElementById('dl-video').href = `/download/${jobId}/video`;
            return;
        }

        // Update steps UI
        const steps = document.querySelectorAll('.step');
        steps.forEach((el) => {
            const s = parseInt(el.dataset.step);
            el.classList.remove('active', 'done');
            if (s < job.step) el.classList.add('done');
            else if (s === job.step) el.classList.add('active');
        });

        // Overall progress
        const overall = job.overall_progress || 0;
        progressFill.style.width = Math.min(100, overall) + '%';
        progressPct.textContent = overall + '%';
        progressStep.textContent = job.step_name || '处理中...';

        if (job.eta_seconds !== undefined) {
            progressEta.textContent = formatEta(job.eta_seconds);
        }
    };

    ws.onerror = () => showError('连接中断');
    ws.onclose = () => {};
}

// ===== Burn subtitles (Phase 2) =====
document.getElementById('burn-btn').addEventListener('click', async () => {
    if (!currentJobId) return;

    const burnBtn = document.getElementById('burn-btn');
    const burnProgress = document.getElementById('burn-progress');
    const burnStatusText = document.getElementById('burn-status-text');

    burnBtn.disabled = true;
    burnBtn.textContent = '合成中...';
    burnProgress.hidden = false;

    try {
        const resp = await fetch(`/burn/${currentJobId}`, { method: 'POST' });
        const data = await resp.json();

        if (data.error) {
            burnStatusText.textContent = '合成失败: ' + data.error;
            burnBtn.disabled = false;
            burnBtn.textContent = '重试合成';
            return;
        }

        pollBurnStatus(currentJobId, burnBtn, burnProgress, burnStatusText);
    } catch (e) {
        burnStatusText.textContent = '合成失败: ' + e.message;
        burnBtn.disabled = false;
        burnBtn.textContent = '重试合成';
    }
});

function pollBurnStatus(jobId, burnBtn, burnProgress, burnStatusText) {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${location.host}/ws/${jobId}`);

    ws.onmessage = (event) => {
        const job = JSON.parse(event.data);

        if (job.burn_status === 'done') {
            burnProgress.hidden = true;
            burnBtn.hidden = true;
            document.getElementById('dl-video').hidden = false;
            ws.close();
            return;
        }

        if (job.burn_status === 'error') {
            burnStatusText.textContent = '合成失败: ' + (job.burn_error || '未知错误');
            burnBtn.disabled = false;
            burnBtn.textContent = '重试合成';
            ws.close();
            return;
        }

        burnStatusText.textContent = '合成中，请稍候...';
    };

    ws.onerror = () => {
        burnStatusText.textContent = '连接中断';
    };
}

// ===== Section switching =====
function showSection(name) {
    uploadSection.hidden = name !== 'upload';
    progressSection.hidden = name !== 'progress';
    errorSection.hidden = name !== 'error';
    doneSection.hidden = name !== 'done';
}

function showError(msg) {
    errorMsg.textContent = msg;
    showSection('error');
}

// ===== Retry / New =====
document.getElementById('retry-btn').addEventListener('click', resetUI);
document.getElementById('new-btn').addEventListener('click', resetUI);

document.getElementById('cleanup-btn').addEventListener('click', async () => {
    if (!currentJobId) { resetUI(); return; }
    try {
        await fetch(`/job/${currentJobId}`, { method: 'DELETE' });
    } catch {}
    resetUI();
});

function resetUI() {
    selectedFile = null;
    currentJobId = null;
    localStorage.removeItem('chaossubs_job_id');
    fileInput.value = '';
    fileInfo.hidden = true;
    dropZone.hidden = false;
    uploadBtn.disabled = true;
    uploadBtn.textContent = '开始处理';
    progressFill.style.width = '0%';
    progressPct.textContent = '0%';
    progressStep.textContent = '准备中...';
    progressEta.textContent = '';
    document.querySelectorAll('.step').forEach(el => el.classList.remove('active', 'done'));

    // Reset burn state
    const burnBtn = document.getElementById('burn-btn');
    burnBtn.hidden = false;
    burnBtn.disabled = false;
    burnBtn.textContent = '合成带字幕视频';
    document.getElementById('burn-progress').hidden = true;
    document.getElementById('dl-video').hidden = true;

    showSection('upload');
}

// ===== Restore job from localStorage =====
(function restoreJob() {
    const savedJobId = localStorage.getItem('chaossubs_job_id');
    if (!savedJobId) return;

    fetch(`/job/${savedJobId}`)
        .then(r => r.json())
        .then(job => {
            if (job.error) {
                localStorage.removeItem('chaossubs_job_id');
                resetUI();
                return;
            }

            currentJobId = savedJobId;

            if (job.status === 'done') {
                if (job.file_name) {
                    uploadFileInfo.textContent = `视频导入成功 — ${job.file_name}`;
                }
                showSection('done');
                document.getElementById('dl-original-srt').href = `/download/${savedJobId}/original-srt`;
                document.getElementById('dl-srt').href = `/download/${savedJobId}/srt`;
                document.getElementById('dl-video').href = `/download/${savedJobId}/video`;

                if (job.burn_status === 'done') {
                    document.getElementById('burn-btn').hidden = true;
                    document.getElementById('dl-video').hidden = false;
                }
                return;
            }

            if (job.status === 'error') {
                showError(job.error || '处理失败');
                return;
            }

            // Still processing — reconnect WebSocket
            if (job.file_name) {
                uploadFileInfo.textContent = `视频导入成功 — ${job.file_name}`;
            }
            showSection('progress');
            connectWebSocket(savedJobId);
        })
        .catch(() => {
            localStorage.removeItem('chaossubs_job_id');
            resetUI();
        });
})();
