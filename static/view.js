/**
 * View — DOM rendering. Reacts to State changes.
 */
const View = (() => {
    const els = {
        disconnectBanner: document.getElementById('disconnect-banner'),
        dropZone: document.getElementById('drop-zone'),
        fileInput: document.getElementById('file-input'),
        fileInfo: document.getElementById('file-info'),
        fileName: document.getElementById('file-name'),
        uploadBtn: document.getElementById('upload-btn'),
        jobList: document.getElementById('job-list'),
    };

    function formatSize(bytes) {
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
        return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
    }

    function formatEta(seconds) {
        if (seconds < 0) return '计算中...';
        if (seconds < 30) return '即将完成';
        if (seconds < 90) return '约 1 分钟';
        const mins = Math.ceil(seconds / 60);
        if (mins < 60) return `约 ${mins} 分钟`;
        const hours = Math.floor(mins / 60);
        const remainMins = mins % 60;
        return remainMins ? `约 ${hours}h ${remainMins}m` : `约 ${hours}h`;
    }

    function formatTime(ts) {
        if (!ts) return '';
        return new Date(ts * 1000).toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    }

    const statusLabels = {
        completed: '已完成', processing: '进行中', queuing: '排队中',
        paused: '已暂停', failed: '失败', corrupted: '已损坏',
    };

    const stepNames = ['提取音频', '语音识别', '时间轴校正', '翻译字幕', '润色优化'];

    const stepStatusClass = {
        'pending': 'pip-pending',
        'queuing': 'pip-queuing',
        'running': 'pip-running',
        'done': 'pip-done',
        'error': 'pip-error',
    };

    function init() {
        State.observe('serverOnline', online => { els.disconnectBanner.hidden = online; });

        State.observe('currentTab', tab => {
            document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.toggle('active', c.id === `tab-${tab}`));
        });

        State.observe('selectedFile', file => {
            if (file) {
                els.fileName.textContent = `${file.name} (${formatSize(file.size)})`;
                els.fileInfo.hidden = false;
                els.dropZone.hidden = true;
                els.uploadBtn.hidden = false;
            } else {
                els.fileInfo.hidden = true;
                els.dropZone.hidden = false;
                els.uploadBtn.hidden = true;
            }
        });

        State.observe('uploading', up => {
            if (up) {
                els.uploadBtn.disabled = true;
                els.uploadBtn.textContent = '提交中...';
            } else {
                els.uploadBtn.disabled = false;
                els.uploadBtn.textContent = '提交任务';
            }
        });

        State.observe('jobList', renderJobList);
    }

    function renderJobList(jobs) {
        if (!jobs) return;

        if (jobs.length === 0) {
            els.jobList.innerHTML = '<div class="empty-state"><p>📭</p><p>暂无任务</p></div>';
            return;
        }

        els.jobList.innerHTML = jobs.map(job => renderJobCard(job)).join('');
    }

    function renderJobCard(job) {
        const badge = statusLabels[job.status] || job.status;

        let body = '';

        if (job.status === 'processing') {
            const pct = job.overall_progress || 0;
            const eta = job.eta_seconds;
            const steps = job.steps || {};

            const statusText = { pending: '待执行', queuing: '排队中', running: '运行中', done: '已完成', error: '失败' };

            const pips = stepNames.map((name, i) => {
                const stepData = steps[String(i + 1)] || {};
                const st = stepData.status || 'pending';
                const cls = stepStatusClass[st] || 'pip-pending';
                return `<div class="job-step" data-step="${i+1}">
                    <div class="job-step-dot ${cls}"></div>
                    <span class="job-step-name">${name}</span>
                    <span class="job-step-status ${cls}">${statusText[st] || ''}</span>
                </div>`;
            }).join('');

            body = `
                <div class="job-progress">
                    <div class="job-steps-row">${pips}</div>
                    <div class="job-progress-info">
                        <span class="job-progress-pct">${pct}%</span>
                        ${eta !== undefined && eta >= 0 ? `<span class="job-progress-eta">${formatEta(eta)}</span>` : ''}
                    </div>
                </div>`;
        }

        if (job.status === 'completed') {
            body = `
                <div class="job-done">
                    <div class="job-downloads">
                        <a class="job-dl-btn" href="/download/${job.job_id}/original-srt" download>📄 原始字幕</a>
                        <a class="job-dl-btn" href="/download/${job.job_id}/srt" download>🌏 中文字幕</a>
                    </div>
                </div>`;
        }

        if (job.status === 'queuing') {
            body = `<div class="job-error" style="color:var(--warning)">排队等待中，前方有任务正在执行...</div>`;
        }

        if (job.status === 'failed') {
            body = `<div class="job-error">${job.error || '处理失败'}</div>`;
        }

        if (job.status === 'paused') {
            const stage = job.current_stage || '';
            const stageMap = {
                upload: '视频导入', extract_audio: '提取音频', transcribe: '语音识别',
                correct_timing: '时间轴校正', translate: '翻译字幕', polish: '润色优化',
            };
            body = `<div class="job-error" style="color:var(--warning)">暂停于: ${stageMap[stage] || stage}</div>`;
        }

        let footer = '';
        if (job.status === 'processing') {
            footer = `<button class="btn-resume" disabled>运行中</button>`;
        } else if (job.status === 'queuing') {
            footer = `<button class="btn-resume" disabled>排队中</button>`;
        } else if (job.status === 'paused') {
            footer = `
                <button class="btn-resume" data-action="resume" data-id="${job.job_id}">恢复</button>
                <button class="btn-delete" data-action="delete" data-id="${job.job_id}">删除</button>`;
        } else if (job.status === 'completed') {
            footer = `<button class="btn-delete" data-action="delete" data-id="${job.job_id}">删除</button>`;
        } else {
            footer = `<button class="btn-delete" data-action="delete" data-id="${job.job_id}">删除</button>`;
        }

        return `
            <div class="job-card fade-in" data-job-id="${job.job_id}">
                <div class="job-card-header">
                    <span class="job-card-name">${job.display_name}</span>
                    <span class="job-card-badge badge-${job.status}">${badge}</span>
                </div>
                <div class="job-card-meta">${job.created_at ? formatTime(job.created_at) : ''}</div>
                ${body}
                <div class="job-card-footer">${footer}</div>
            </div>`;
    }

    function updateJobCard(jobId, jobData) {
        const card = document.querySelector(`.job-card[data-job-id="${jobId}"]`);
        if (!card) return;

        // Only update the inner parts, not replace the whole card
        const badge = card.querySelector('.job-card-badge');
        if (badge) {
            const statusLabel = {completed:'已完成', processing:'进行中', paused:'已暂停', failed:'失败', corrupted:'已损坏'}[jobData.status] || jobData.status;
            badge.className = `job-card-badge badge-${jobData.status}`;
            badge.textContent = statusLabel;
        }

        // Update progress section
        const progress = card.querySelector('.job-progress');
        if (progress && jobData.status === 'processing') {
            const steps = jobData.steps || {};
            const pct = jobData.overall_progress || 0;
            const eta = jobData.eta_seconds;

            const statusText = { pending: '待执行', queuing: '排队中', running: '运行中', done: '已完成', error: '失败' };
            // Update dots + status text
            card.querySelectorAll('.job-step').forEach((stepEl) => {
                const i = parseInt(stepEl.dataset.step);
                const st = (steps[String(i)] || {}).status || 'pending';
                const dot = stepEl.querySelector('.job-step-dot');
                const label = stepEl.querySelector('.job-step-status');
                if (dot) dot.className = `job-step-dot pip-${st}`;
                if (label) { label.className = `job-step-status pip-${st}`; label.textContent = statusText[st] || ''; }
            });

            // Update pct
            const pctEl = card.querySelector('.job-progress-pct');
            if (pctEl) pctEl.textContent = pct + '%';

            // Update eta
            const etaEl = card.querySelector('.job-progress-eta');
            if (etaEl) {
                etaEl.textContent = (eta !== undefined && eta >= 0) ? formatEta(eta) : '';
            } else if (eta !== undefined && eta >= 0) {
                const info = card.querySelector('.job-progress-info');
                if (info) info.insertAdjacentHTML('beforeend', `<span class="job-progress-eta">${formatEta(eta)}</span>`);
            }
        }

        // If status changed to done/error, do a full replace (once)
        if (jobData.status === 'completed' || jobData.status === 'failed') {
            card.outerHTML = renderJobCard(jobData);
        }
    }

    return { init, els, formatSize, formatEta, updateJobCard, renderJobList };
})();
