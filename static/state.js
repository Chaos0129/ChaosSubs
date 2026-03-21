/**
 * Model — Reactive state management with observer pattern.
 * State changes trigger bound callbacks automatically.
 */
const State = (() => {
    const _data = {
        // App state
        currentTab: 'new',
        serverOnline: true,

        // Upload state
        selectedFile: null,
        uploading: false,

        // Current job
        currentJobId: null,
        jobStatus: 'idle', // idle, processing, done, error
        jobStep: 0,
        jobStepName: '',
        jobProgress: 0,
        jobEta: -1,
        jobFileName: '',
        jobError: null,

        // Job list (history tab)
        jobList: [],
        jobListLoading: false,
    };

    const _observers = {};

    function get(key) {
        return _data[key];
    }

    function set(key, value) {
        if (_data[key] === value) return;
        _data[key] = value;
        _notify(key, value);
    }

    function setMany(obj) {
        for (const [key, value] of Object.entries(obj)) {
            _data[key] = value;
        }
        for (const key of Object.keys(obj)) {
            _notify(key, _data[key]);
        }
    }

    function observe(key, callback) {
        if (!_observers[key]) _observers[key] = [];
        _observers[key].push(callback);
        // Fire immediately with current value
        callback(_data[key]);
    }

    function _notify(key, value) {
        if (_observers[key]) {
            _observers[key].forEach(cb => cb(value));
        }
    }

    function getAll() {
        return { ..._data };
    }

    return { get, set, setMany, observe, getAll };
})();
