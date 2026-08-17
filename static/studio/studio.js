(function () {
    function request(url, options) {
        options = options || {};
        options.headers = Object.assign({
            "Content-Type": "application/json"
        }, options.headers || {});
        return fetch(url, options).then(function (response) {
            return response.json().catch(function () {
                return {success: false, msg: "服务器返回了无效响应"};
            }).then(function (payload) {
                if (!response.ok || payload.success === false) {
                    throw new Error(payload.msg || "请求失败");
                }
                return payload;
            });
        });
    }

    function escapeHtml(value) {
        return String(value == null ? "" : value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function statusClass(status) {
        var map = {
            SUCCEEDED: "green",
            PROCESSING: "",
            SUBMITTED: "",
            PENDING: "gray",
            FAILED: "red",
            CANCELLED: "orange"
        };
        return map[status] || "gray";
    }

    function statusText(status) {
        var map = {
            SUCCEEDED: "已完成",
            PROCESSING: "处理中",
            SUBMITTED: "已提交",
            PENDING: "待提交",
            FAILED: "失败",
            CANCELLED: "已取消"
        };
        return map[status] || status || "未知";
    }

    function toast(message, type) {
        if (window.layer) {
            layer.msg(message, {icon: type === "error" ? 2 : 1, time: 2200});
        } else {
            window.alert(message);
        }
    }

    function initLayer() {
        if (window.layui) {
            layui.use(["layer", "form"], function () {
                window.layer = layui.layer;
                window.studioForm = layui.form;
            });
        }
    }

    function valueForInput(value, valueType) {
        if (value == null) return "";
        if (valueType === "json" && typeof value !== "string") return JSON.stringify(value);
        return String(value);
    }

    function renderDynamicFields(container, schema, reservedFields) {
        reservedFields = reservedFields || [];
        schema = (schema || []).filter(function (item) {
            return item.enabled !== false && reservedFields.indexOf(item.field) === -1;
        });
        if (!schema.length) {
            container.innerHTML = '<div class="studio-empty studio-empty-compact">当前模型没有额外可编辑字段</div>';
            return;
        }
        container.innerHTML = schema.map(function (item) {
            var type = String(item.value_type || "string").toLowerCase();
            var label = item.label || item.field;
            var hint = item.hint ? '<div class="studio-field-hint">' + escapeHtml(item.hint) + '</div>' : "";
            var input;
            if (type === "boolean" || type === "bool") {
                var checked = String(item.value).toLowerCase() === "true" || item.value === true;
                input = '<label class="studio-checkbox"><input type="checkbox" data-dynamic-field="1" data-field="' +
                    escapeHtml(item.field) + '" data-value-type="boolean" ' + (checked ? "checked" : "") + '>启用</label>';
            } else if (type === "json" || type === "array" || type === "object") {
                input = '<textarea class="layui-textarea studio-dynamic-input" rows="2" data-dynamic-field="1" data-field="' +
                    escapeHtml(item.field) + '" data-value-type="json" placeholder="JSON">' +
                    escapeHtml(valueForInput(item.value, "json")) + '</textarea>';
            } else {
                input = '<input class="layui-input studio-dynamic-input" data-dynamic-field="1" data-field="' +
                    escapeHtml(item.field) + '" data-value-type="' + escapeHtml(type) + '" value="' +
                    escapeHtml(valueForInput(item.value, type)) + '">';
            }
            return '<div class="studio-dynamic-field"><label class="studio-field-label">' +
                escapeHtml(label) + '<span class="studio-field-code">' + escapeHtml(item.field) + '</span></label>' +
                input + hint + '</div>';
        }).join("");
    }

    function collectDynamicFields(container) {
        var output = {};
        container.querySelectorAll("[data-dynamic-field]").forEach(function (input) {
            var field = input.dataset.field;
            var value;
            if (input.type === "checkbox") {
                value = input.checked;
            } else {
                value = input.value;
                if (input.dataset.valueType === "json" && value.trim()) {
                    try {
                        value = JSON.parse(value);
                    } catch (error) {
                        throw new Error("字段 " + field + " 必须填写合法 JSON");
                    }
                }
            }
            if (value !== "" && value !== null && !(Array.isArray(value) && !value.length)) {
                output[field] = value;
            }
        });
        return output;
    }

    window.Studio = {
        request: request,
        escapeHtml: escapeHtml,
        statusClass: statusClass,
        statusText: statusText,
        toast: toast,
        initLayer: initLayer,
        renderDynamicFields: renderDynamicFields,
        collectDynamicFields: collectDynamicFields
    };
    initLayer();
})();
