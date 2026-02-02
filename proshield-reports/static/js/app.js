/**
 * Proshield Reports - Main Application JavaScript
 * PWA Support, Offline Handling, Common Functions
 */

// ==========================================
// Toast Notifications
// ==========================================
function showToast(message, type = 'info', duration = 4000) {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;

    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(20px)';
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

// Make showToast globally available
window.showToast = showToast;

// ==========================================
// Loading Overlay
// ==========================================
function showLoading(show = true) {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) {
        overlay.classList.toggle('active', show);
    }
}

window.showLoading = showLoading;

// ==========================================
// Offline Storage
// ==========================================
const OfflineStorage = {
    REPORTS_KEY: 'offlineReports',

    saveReport(report) {
        const reports = this.getReports();
        report.offlineId = Date.now();
        reports.push(report);
        localStorage.setItem(this.REPORTS_KEY, JSON.stringify(reports));
        return report.offlineId;
    },

    getReports() {
        return JSON.parse(localStorage.getItem(this.REPORTS_KEY) || '[]');
    },

    removeReport(offlineId) {
        const reports = this.getReports().filter(r => r.offlineId !== offlineId);
        localStorage.setItem(this.REPORTS_KEY, JSON.stringify(reports));
    },

    clearAll() {
        localStorage.removeItem(this.REPORTS_KEY);
    },

    count() {
        return this.getReports().length;
    }
};

window.OfflineStorage = OfflineStorage;

// ==========================================
// Network Status
// ==========================================
function updateOnlineStatus() {
    const indicator = document.getElementById('offlineIndicator');
    if (indicator) {
        indicator.classList.toggle('active', !navigator.onLine);
    }

    if (navigator.onLine && OfflineStorage.count() > 0) {
        showToast('התקשורת חזרה - ניתן לסנכרן דוחות', 'info');
    }
}

window.addEventListener('online', updateOnlineStatus);
window.addEventListener('offline', updateOnlineStatus);

// ==========================================
// Form Utilities
// ==========================================
function validateEmail(email) {
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return re.test(email);
}

function validateRequired(value) {
    return value && value.trim().length > 0;
}

function formatNumber(num, decimals = 2) {
    return parseFloat(num).toFixed(decimals);
}

function formatDate(isoString) {
    if (!isoString) return '';
    const date = new Date(isoString);
    return date.toLocaleDateString('he-IL', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ==========================================
// File Utilities
// ==========================================
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function getFileExtension(filename) {
    return filename.slice((filename.lastIndexOf('.') - 1 >>> 0) + 2).toLowerCase();
}

function isImageFile(filename) {
    const extensions = ['jpg', 'jpeg', 'png', 'gif', 'webp'];
    return extensions.includes(getFileExtension(filename));
}

function isPdfFile(filename) {
    return getFileExtension(filename) === 'pdf';
}

// ==========================================
// Image Compression (Client-side)
// ==========================================
function compressImage(file, maxWidth = 1920, quality = 0.85) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = (e) => {
            const img = new Image();
            img.onload = () => {
                const canvas = document.createElement('canvas');
                let { width, height } = img;

                // Calculate new dimensions
                if (width > maxWidth) {
                    height = (height * maxWidth) / width;
                    width = maxWidth;
                }

                canvas.width = width;
                canvas.height = height;

                const ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0, width, height);

                canvas.toBlob(
                    (blob) => {
                        resolve(new File([blob], file.name, {
                            type: 'image/jpeg',
                            lastModified: Date.now()
                        }));
                    },
                    'image/jpeg',
                    quality
                );
            };
            img.onerror = reject;
            img.src = e.target.result;
        };
        reader.onerror = reject;
        reader.readAsDataURL(file);
    });
}

window.compressImage = compressImage;

// ==========================================
// API Helper
// ==========================================
const API = {
    async get(url) {
        try {
            const response = await fetch(url);
            if (!response.ok) throw new Error('Network response was not ok');
            return await response.json();
        } catch (error) {
            console.error('API GET error:', error);
            throw error;
        }
    },

    async post(url, data, isFormData = false) {
        try {
            const options = {
                method: 'POST',
                body: isFormData ? data : JSON.stringify(data)
            };

            if (!isFormData) {
                options.headers = { 'Content-Type': 'application/json' };
            }

            const response = await fetch(url, options);
            return await response.json();
        } catch (error) {
            console.error('API POST error:', error);
            throw error;
        }
    },

    async delete(url) {
        try {
            const response = await fetch(url, { method: 'DELETE' });
            return await response.json();
        } catch (error) {
            console.error('API DELETE error:', error);
            throw error;
        }
    }
};

window.API = API;

// ==========================================
// PWA Install Prompt
// ==========================================
let deferredPrompt;

window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;

    // Show install button if it exists
    const installBtn = document.getElementById('installPwaBtn');
    if (installBtn) {
        installBtn.style.display = 'block';
    }
});

window.addEventListener('appinstalled', () => {
    console.log('PWA installed');
    deferredPrompt = null;
    showToast('האפליקציה הותקנה בהצלחה!', 'success');
});

function installPWA() {
    if (deferredPrompt) {
        deferredPrompt.prompt();
        deferredPrompt.userChoice.then((choiceResult) => {
            if (choiceResult.outcome === 'accepted') {
                console.log('User accepted the install prompt');
            }
            deferredPrompt = null;
        });
    }
}

window.installPWA = installPWA;

// ==========================================
// Debounce Utility
// ==========================================
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

window.debounce = debounce;

// ==========================================
// Initialize on DOM Ready
// ==========================================
document.addEventListener('DOMContentLoaded', () => {
    // Update online status indicator
    updateOnlineStatus();

    // Check for offline reports
    const offlineCount = OfflineStorage.count();
    if (offlineCount > 0) {
        console.log(`${offlineCount} offline reports pending sync`);
    }
});

// ==========================================
// Export for modules
// ==========================================
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        showToast,
        showLoading,
        OfflineStorage,
        API,
        compressImage,
        formatDate,
        formatFileSize,
        escapeHtml,
        debounce
    };
}
