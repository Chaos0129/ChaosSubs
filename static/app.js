/**
 * ViewModel — Business logic, API, events.
 */
const ViewModel = (() => {
    const _wsMap = {}; // jobId -> WebSocket

    const API = {
        async upload(file, language) {
            const fd = new FormData();
            fd.append('file', file);
            fd.append('language', language);
            return (await fetch('/upload', { method: 'POST', body: fd })).json();
        },
        async listJobs() { return (await fetch('/jobs')).json(); },
        async getJob(id) { return (await fetch(`/job/${id}`)).json(); },
        async deleteJob(id) { await fetch(`/job/${id}`, { method: 'DELETE' }); },
        async resumeJob(id) { return (await fetch(`/job/${id}/resume`, { method: 'POST' })).json(); },
    };

    // ===== Actions =====

    function switchTab(tab) {
        State.set('currentTab', tab);
        if (tab === 'tasks') loadJobs();
    }

    function selectFile(file) { State.set('selectedFile', file); }

    function clearFile() {
        State.set('selectedFile', null);
        View.els.fileInput.value = '';
    }

    async function submitTask() {
        const file = State.get('selectedFile');
        if (!file) return;

        State.set('uploading', true);
        const lang = document.getElementById('source-lang').value;

        try {
            const data = await API.upload(file, lang);
            State.set('uploading', false);

            if (data.error) {
                alert('上传失败: ' + data.error);
                return;
            }

            // Reset upload form
            State.set('selectedFile', null);
            View.els.fileInput.value = '';

            // Switch to tasks tab
            switchTab('tasks');

        } catch (e) {
            State.set('uploading', false);
            alert('上传失败: ' + e.message);
        }
    }

    async function loadJobs() {
        const jobs = await API.listJobs();
        State.set('jobList', jobs);

        // Connect WebSocket for any processing jobs
        jobs.forEach(job => {
            if (job.status === 'processing' && !_wsMap[job.job_id]) {
                connectJobWs(job.job_id);
            }
        });
    }

    function connectJobWs(jobId) {
        if (_wsMap[jobId]) { try { _wsMap[jobId].close(); } catch {} }

        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const ws = new WebSocket(`${protocol}//${location.host}/ws/${jobId}`);
        _wsMap[jobId] = ws;

        ws.onmessage = (event) => {
            const job = JSON.parse(event.data);

            // Build card data
            const cardData = {
                job_id: jobId,
                display_name: job.file_name ? `${job.file_name.replace(/\.[^.]+$/, '')} (${jobId})` : jobId,
                status: job.status === 'done' ? 'completed' : (job.status || 'queuing'),
                created_at: job.created_at,
                step: job.current_step,
                step_name: job.step_name,
                overall_progress: job.overall_progress,
                eta_seconds: job.eta_seconds,
                error: job.error,
                current_stage: job.current_stage,
                steps: job.steps || {},
            };

            View.updateJobCard(jobId, cardData);

            if (job.status === 'done' || job.status === 'error') {
                delete _wsMap[jobId];
                // Reload full list to get accurate state
                setTimeout(loadJobs, 500);
            }
        };

        ws.onerror = () => { delete _wsMap[jobId]; };
        ws.onclose = () => { delete _wsMap[jobId]; };
    }

    async function deleteJob(jobId) {
        if (!confirm('确认删除此任务及所有数据？')) return;
        await API.deleteJob(jobId);
        loadJobs();
    }

    async function resumeJob(jobId) {
        const data = await API.resumeJob(jobId);
        if (data.error) { alert('恢复失败: ' + data.error); return; }
        loadJobs();
    }

    function startHealthCheck() {
        setInterval(async () => {
            try {
                await fetch('/health', { signal: AbortSignal.timeout(3000) });
                State.set('serverOnline', true);
            } catch { State.set('serverOnline', false); }
        }, 15000);
    }

    return { switchTab, selectFile, clearFile, submitTask, loadJobs, deleteJob, resumeJob, startHealthCheck };
})();


// ===== Init =====
(function init() {
    View.init();

    // Tabs
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => ViewModel.switchTab(tab.dataset.tab));
    });

    // File selection
    View.els.dropZone.addEventListener('click', () => View.els.fileInput.click());
    View.els.dropZone.addEventListener('dragover', e => { e.preventDefault(); View.els.dropZone.classList.add('dragover'); });
    View.els.dropZone.addEventListener('dragleave', () => View.els.dropZone.classList.remove('dragover'));
    View.els.dropZone.addEventListener('drop', e => {
        e.preventDefault();
        View.els.dropZone.classList.remove('dragover');
        if (e.dataTransfer.files.length) ViewModel.selectFile(e.dataTransfer.files[0]);
    });
    View.els.fileInput.addEventListener('change', () => {
        if (View.els.fileInput.files.length) ViewModel.selectFile(View.els.fileInput.files[0]);
    });
    document.getElementById('clear-btn').addEventListener('click', ViewModel.clearFile);

    // Upload
    View.els.uploadBtn.addEventListener('click', ViewModel.submitTask);

    // Job list actions (event delegation)
    document.getElementById('job-list').addEventListener('click', e => {
        const btn = e.target.closest('[data-action]');
        if (!btn) return;
        const { action, id } = btn.dataset;
        if (action === 'delete') ViewModel.deleteJob(id);
        else if (action === 'resume') ViewModel.resumeJob(id);
    });

    // Health check
    ViewModel.startHealthCheck();

    // Auto-load tasks tab if there are running jobs
    ViewModel.loadJobs().then(() => {
        const jobs = State.get('jobList');
        if (jobs && jobs.some(j => j.status === 'processing')) {
            ViewModel.switchTab('tasks');
        }
    });
})();
