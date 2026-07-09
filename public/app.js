document.addEventListener('DOMContentLoaded', () => {
    const urlInput = document.getElementById('url-input');
    const processBtn = document.getElementById('process-btn');
    const resultSection = document.getElementById('result-section');
    const errorMsg = document.getElementById('error-message');
    
    const videoThumb = document.getElementById('video-thumb');
    const videoTitle = document.getElementById('video-title');
    const qualitySelect = document.getElementById('quality-select');
    const downloadBtn = document.getElementById('download-btn');

    let currentUrl = '';

    const showError = (msg) => {
        errorMsg.textContent = msg;
        errorMsg.classList.remove('hidden');
        resultSection.classList.add('hidden');
    };

    const hideError = () => {
        errorMsg.classList.add('hidden');
    };

    processBtn.addEventListener('click', async () => {
        const url = urlInput.value.trim();
        if (!url) {
            showError("Please enter a valid YouTube URL.");
            return;
        }

        hideError();
        processBtn.classList.add('loading');
        processBtn.disabled = true;
        resultSection.classList.add('hidden');

        try {
            const response = await fetch(`/api/process?url=${encodeURIComponent(url)}`);
            const data = await response.json();

            if (!response.ok) throw new Error(data.error || 'Failed to process video');

            currentUrl = url;
            
            // Populate video info
            videoTitle.textContent = data.title;
            videoThumb.src = data.thumbnail || '';

            // Populate quality dropdown
            qualitySelect.innerHTML = '<option value="">Select Quality</option>';
            data.formats.forEach(format => {
                const option = document.createElement('option');
                option.value = format.id;
                
                let label = format.resolution;
                if (format.fps) label += ` ${format.fps}fps`;
                if (format.ext) label += ` (${format.ext})`;
                if (format.note) label += ` - ${format.note}`;
                if (!format.has_audio) label += ` (Merges Audio)`;
                
                option.textContent = label;
                qualitySelect.appendChild(option);
            });

            // Show result section
            resultSection.classList.remove('hidden');

        } catch (err) {
            showError(err.message);
        } finally {
            processBtn.classList.remove('loading');
            processBtn.disabled = false;
        }
    });

    downloadBtn.addEventListener('click', () => {
        const formatId = qualitySelect.value;
        if (!formatId) {
            showError("Please select a video quality before downloading.");
            return;
        }

        hideError();
        downloadBtn.classList.add('loading');
        downloadBtn.disabled = true;

        // Start download by redirecting to the endpoint
        // This triggers a file download in the browser
        const downloadUrl = `/api/download?url=${encodeURIComponent(currentUrl)}&format_id=${encodeURIComponent(formatId)}`;
        
        // We can use an iframe or just window.location to trigger download without leaving the page
        const a = document.createElement('a');
        a.href = downloadUrl;
        // The endpoint uses Content-Disposition attachment, so it will download.
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);

        // Reset button state immediately or wait a bit
        setTimeout(() => {
            downloadBtn.classList.remove('loading');
            downloadBtn.disabled = false;
        }, 3000);
    });

    // Enter key to process
    urlInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            processBtn.click();
        }
    });
});
