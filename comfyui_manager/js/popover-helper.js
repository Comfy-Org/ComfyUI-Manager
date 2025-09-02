const hasOwn = function(obj, key) {
    return Object.prototype.hasOwnProperty.call(obj, key);
};

const isNum = function(num) {
    if (typeof num !== 'number' || isNaN(num)) {
        return false;
    }
    const isInvalid = function(n) {
        if (n === Number.MAX_VALUE || n === Number.MIN_VALUE || n === Number.NEGATIVE_INFINITY || n === Number.POSITIVE_INFINITY) {
            return true;
        }
        return false;
    };
    if (isInvalid(num)) {
        return false;
    }
    return true;
};

const toNum = (num) => {
    if (typeof (num) !== 'number') {
        num = parseFloat(num);
    }
    if (isNaN(num)) {
        num = 0;
    }
    num = Math.round(num);
    return num;
};

const clamp = function(value, min, max) {
    return Math.max(min, Math.min(max, value));
};

const isWindow = (obj) => {
    return Boolean(obj && obj === obj.window);
};

const isDocument = (obj) => {
    return Boolean(obj && obj.nodeType === 9);
};

const isElement = (obj) => {
    return Boolean(obj && obj.nodeType === 1);
};

// ===========================================================================================

export const toRect = (obj) => {
    if (obj) {
        return {
            left: toNum(obj.left || obj.x),
            top: toNum(obj.top || obj.y),
            width: toNum(obj.width),
            height: toNum(obj.height)
        };
    }
    return {
        left: 0,
        top: 0,
        width: 0,
        height: 0
    };
};

export const getElement = (selector) => {
    if (typeof selector === 'string' && selector) {
        if (selector.startsWith('#')) {
            return document.getElementById(selector.slice(1));
        }
        return document.querySelector(selector);
    }

    if (isDocument(selector)) {
        return selector.body;
    }
    if (isElement(selector)) {
        return selector;
    }
};

export const getRect = (target, fixed) => {
    if (!target) {
        return toRect();
    }

    if (isWindow(target)) {
        return {
            left: 0,
            top: 0,
            width: window.innerWidth,
            height: window.innerHeight
        };
    }

    const elem = getElement(target);
    if (!elem) {
        return toRect(target);
    }

    const br = elem.getBoundingClientRect();
    const rect = toRect(br);

    // fix offset
    if (!fixed) {
        rect.left += window.scrollX;
        rect.top += window.scrollY;
    }

    rect.width = elem.offsetWidth;
    rect.height = elem.offsetHeight;

    return rect;
};

// ===========================================================================================

const calculators = {

    bottom: (info, containerRect, targetRect) => {
        info.space = containerRect.top + containerRect.height - targetRect.top - targetRect.height - info.height;
        info.top = targetRect.top + targetRect.height;
        info.left = Math.round(targetRect.left + targetRect.width * 0.5 - info.width * 0.5);
    },

    top: (info, containerRect, targetRect) => {
        info.space = targetRect.top - info.height - containerRect.top;
        info.top = targetRect.top - info.height;
        info.left = Math.round(targetRect.left + targetRect.width * 0.5 - info.width * 0.5);
    },

    right: (info, containerRect, targetRect) => {
        info.space = containerRect.left + containerRect.width - targetRect.left - targetRect.width - info.width;
        info.top = Math.round(targetRect.top + targetRect.height * 0.5 - info.height * 0.5);
        info.left = targetRect.left + targetRect.width;
    },

    left: (info, containerRect, targetRect) => {
        info.space = targetRect.left - info.width - containerRect.left;
        info.top = Math.round(targetRect.top + targetRect.height * 0.5 - info.height * 0.5);
        info.left = targetRect.left - info.width;
    }
};

// with order
export const getDefaultPositions = () => {
    return Object.keys(calculators);
};

const calculateSpace = (info, containerRect, targetRect) => {
    const calculator = calculators[info.position];
    calculator(info, containerRect, targetRect);
    if (info.space >= 0) {
        info.passed += 1;
    }
};

// ===========================================================================================

const calculateAlignOffset = (info, containerRect, targetRect, alignType, sizeType) => {

    const popoverStart = info[alignType];
    const popoverSize = info[sizeType];

    const containerStart = containerRect[alignType];
    const containerSize = containerRect[sizeType];

    const targetStart = targetRect[alignType];
    const targetSize = targetRect[sizeType];

    const targetCenter = targetStart + targetSize * 0.5;

    // size overflow
    if (popoverSize > containerSize) {
        const overflow = (popoverSize - containerSize) * 0.5;
        info[alignType] = containerStart - overflow;
        info.offset = targetCenter - containerStart + overflow;
        return;
    }

    const space1 = popoverStart - containerStart;
    const space2 = (containerStart + containerSize) - (popoverStart + popoverSize);

    // both side passed, default to center
    if (space1 >= 0 && space2 >= 0) {
        if (info.passed) {
            info.passed += 2;
        }
        info.offset = popoverSize * 0.5;
        return;
    }

    // one side passed
    if (info.passed) {
        info.passed += 1;
    }

    if (space1 < 0) {
        const min = containerStart;
        info[alignType] = min;
        info.offset = targetCenter - min;
        return;
    }

    // space2 < 0
    const max = containerStart + containerSize - popoverSize;
    info[alignType] = max;
    info.offset = targetCenter - max;

};

const calculateHV = (info, containerRect) => {
    if (['top', 'bottom'].includes(info.position)) {
        info.top = clamp(info.top, containerRect.top, containerRect.top + containerRect.height - info.height);
        return ['left', 'width'];
    }
    info.left = clamp(info.left, containerRect.left, containerRect.left + containerRect.width - info.width);
    return ['top', 'height'];
};

const calculateOffset = (info, containerRect, targetRect) => {

    const [alignType, sizeType] = calculateHV(info, containerRect);

    calculateAlignOffset(info, containerRect, targetRect, alignType, sizeType);

    info.offset = clamp(info.offset, 0, info[sizeType]);

};

// ===========================================================================================

const calculateDistance = (info, previousPositionInfo) => {
    if (!previousPositionInfo) {
        return;
    }
    // no change if position no change with previous
    if (info.position === previousPositionInfo.position) {
        return;
    }
    const ax = info.left + info.width * 0.5;
    const ay = info.top + info.height * 0.5;
    const bx = previousPositionInfo.left + previousPositionInfo.width * 0.5;
    const by = previousPositionInfo.top + previousPositionInfo.height * 0.5;
    const dx = Math.abs(ax - bx);
    const dy = Math.abs(ay - by);
    info.distance = Math.round(Math.sqrt(dx * dx + dy * dy));
};

// ===========================================================================================

const calculatePositionInfo = (info, containerRect, targetRect, previousPositionInfo) => {
    calculateSpace(info, containerRect, targetRect);
    calculateOffset(info, containerRect, targetRect);
    calculateDistance(info, previousPositionInfo);
};

// ===========================================================================================

const calculateBestPosition = (containerRect, targetRect, infoMap, withOrder, previousPositionInfo) => {

    // position space: +1
    // align space:
    //    two side passed: +2
    //    one side passed: +1

    const safePassed = 3;

    if (previousPositionInfo) {
        const prevInfo = infoMap[previousPositionInfo.position];
        if (prevInfo) {
            calculatePositionInfo(prevInfo, containerRect, targetRect);
            if (prevInfo.passed >= safePassed) {
                return prevInfo;
            }
            prevInfo.calculated = true;
        }
    }

    const positionList = [];
    Object.values(infoMap).forEach((info) => {
        if (!info.calculated) {
            calculatePositionInfo(info, containerRect, targetRect, previousPositionInfo);
        }
        positionList.push(info);
    });

    positionList.sort((a, b) => {
        if (a.passed !== b.passed) {
            return b.passed - a.passed;
        }

        if (withOrder && a.passed >= safePassed && b.passed >= safePassed) {
            return a.index - b.index;
        }

        if (a.space !== b.space) {
            return b.space - a.space;
        }

        return a.index - b.index;
    });

    // logTable(positionList);

    return positionList[0];
};

// const logTable = (() => {
//     let time_id;
//     return (info) => {
//         clearTimeout(time_id);
//         time_id = setTimeout(() => {
//             console.table(info);
//         }, 10);
//     };
// })();

// ===========================================================================================

const getAllowPositions = (positions, defaultAllowPositions) => {
    if (!positions) {
        return;
    }
    if (Array.isArray(positions)) {
        positions = positions.join(',');
    }
    positions = String(positions).split(',').map((it) => it.trim().toLowerCase()).filter((it) => it);
    positions = positions.filter((it) => defaultAllowPositions.includes(it));
    if (!positions.length) {
        return;
    }
    return positions;
};

const isPositionChanged = (info, previousPositionInfo) => {
    if (!previousPositionInfo) {
        return true;
    }

    if (info.left !== previousPositionInfo.left) {
        return true;
    }

    if (info.top !== previousPositionInfo.top) {
        return true;
    }

    return false;
};

// ===========================================================================================

// const log = (name, time) => {
//     if (time > 0.1) {
//         console.log(name, time);
//     }
// };

export const getBestPosition = (containerRect, targetRect, popoverRect, positions, previousPositionInfo) => {

    const defaultAllowPositions = getDefaultPositions();
    let withOrder = true;
    let allowPositions = getAllowPositions(positions, defaultAllowPositions);
    if (!allowPositions) {
        allowPositions = defaultAllowPositions;
        withOrder = false;
    }

    // console.log('withOrder', withOrder);

    // const start_time = performance.now();

    const infoMap = {};
    allowPositions.forEach((k, i) => {
        infoMap[k] = {
            position: k,
            index: i,

            top: 0,
            left: 0,
            width: popoverRect.width,
            height: popoverRect.height,

            space: 0,

            offset: 0,
            passed: 0,

            distance: 0
        };
    });

    // log('infoMap', performance.now() - start_time);


    const bestPosition = calculateBestPosition(containerRect, targetRect, infoMap, withOrder, previousPositionInfo);

    // check left/top
    bestPosition.changed = isPositionChanged(bestPosition, previousPositionInfo);

    return bestPosition;
};

// ===========================================================================================

const getTemplatePath = (width, height, arrowOffset, arrowSize, borderRadius) => {
    const p = (px, py) => {
        return [px, py].join(',');
    };

    const px = function(num, alignEnd) {
        const floor = Math.floor(num);
        let n = num < floor + 0.5 ? floor + 0.5 : floor + 1.5;
        if (alignEnd) {
            n -= 1;
        }
        return n;
    };

    const pxe = function(num) {
        return px(num, true);
    };

    const ls = [];

    const innerLeft = px(arrowSize);
    const innerRight = pxe(width - arrowSize);
    arrowOffset = clamp(arrowOffset, innerLeft, innerRight);

    const innerTop = px(arrowSize);
    const innerBottom = pxe(height - arrowSize);

    const startPoint = p(innerLeft, innerTop + borderRadius);
    const arrowPoint = p(arrowOffset, 1);

    const LT = p(innerLeft, innerTop);
    const RT = p(innerRight, innerTop);

    const AOT = p(arrowOffset - arrowSize, innerTop);
    const RRT = p(innerRight - borderRadius, innerTop);

    ls.push(`M${startPoint}`);
    ls.push(`V${innerBottom - borderRadius}`);
    ls.push(`Q${p(innerLeft, innerBottom)} ${p(innerLeft + borderRadius, innerBottom)}`);
    ls.push(`H${innerRight - borderRadius}`);
    ls.push(`Q${p(innerRight, innerBottom)} ${p(innerRight, innerBottom - borderRadius)}`);
    ls.push(`V${innerTop + borderRadius}`);

    if (arrowOffset < innerLeft + arrowSize + borderRadius) {
        ls.push(`Q${RT} ${RRT}`);
        ls.push(`H${arrowOffset + arrowSize}`);
        ls.push(`L${arrowPoint}`);
        if (arrowOffset < innerLeft + arrowSize) {
            ls.push(`L${LT}`);
            ls.push(`L${startPoint}`);
        } else {
            ls.push(`L${AOT}`);
            ls.push(`Q${LT} ${startPoint}`);
        }
    } else if (arrowOffset > innerRight - arrowSize - borderRadius) {
        if (arrowOffset > innerRight - arrowSize) {
            ls.push(`L${RT}`);
        } else {
            ls.push(`Q${RT} ${p(arrowOffset + arrowSize, innerTop)}`);
        }
        ls.push(`L${arrowPoint}`);
        ls.push(`L${AOT}`);
        ls.push(`H${innerLeft + borderRadius}`);
        ls.push(`Q${LT} ${startPoint}`);
    } else {
        ls.push(`Q${RT} ${RRT}`);
        ls.push(`H${arrowOffset + arrowSize}`);
        ls.push(`L${arrowPoint}`);
        ls.push(`L${AOT}`);
        ls.push(`H${innerLeft + borderRadius}`);
        ls.push(`Q${LT} ${startPoint}`);
    }
    return ls.join('');
};

const getPathData = function(position, width, height, arrowOffset, arrowSize, borderRadius) {

    const handlers = {

        bottom: () => {
            const d = getTemplatePath(width, height, arrowOffset, arrowSize, borderRadius);
            return {
                d,
                transform: ''
            };
        },

        top: () => {
            const d = getTemplatePath(width, height, width - arrowOffset, arrowSize, borderRadius);
            return {
                d,
                transform: `rotate(180,${width * 0.5},${height * 0.5})`
            };
        },

        left: () => {
            const d = getTemplatePath(height, width, arrowOffset, arrowSize, borderRadius);
            const x = (width - height) * 0.5;
            const y = (height - width) * 0.5;
            return {
                d,
                transform: `translate(${x} ${y}) rotate(90,${height * 0.5},${width * 0.5})`
            };
        },

        right: () => {
            const d = getTemplatePath(height, width, height - arrowOffset, arrowSize, borderRadius);
            const x = (width - height) * 0.5;
            const y = (height - width) * 0.5;
            return {
                d,
                transform: `translate(${x} ${y}) rotate(-90,${height * 0.5},${width * 0.5})`
            };
        }
    };

    return handlers[position]();
};

// ===========================================================================================

// position style cache
const styleCache = {
    // position: '',
    // top: {},
    // bottom: {},
    // left: {},
    // right: {}
};

export const getPositionStyle = (info, options = {}) => {

    const o = {
        bgColor: '#fff',
        borderColor: '#ccc',
        borderRadius: 5,
        arrowSize: 10
    };
    Object.keys(o).forEach((k) => {

        if (hasOwn(options, k)) {
            const d = o[k];
            const v = options[k];

            if (typeof d === 'string') {
                // string
                if (typeof v === 'string' && v) {
                    o[k] = v;
                }
            } else {
                // number
                if (isNum(v) && v >= 0) {
                    o[k] = v;
                }

            }

        }
    });

    const key = [
        info.width,
        info.height,
        info.offset,
        o.arrowSize,
        o.borderRadius,
        o.bgColor,
        o.borderColor
    ].join('-');

    const positionCache = styleCache[info.position];
    if (positionCache && key === positionCache.key) {
        const st = positionCache.style;
        st.changed = styleCache.position !== info.position;
        styleCache.position = info.position;
        return st;
    }

    // console.log(options);

    const data = getPathData(info.position, info.width, info.height, info.offset, o.arrowSize, o.borderRadius);
    // console.log(data);

    const viewBox = [0, 0, info.width, info.height].join(' ');
    const svg = [
        `<svg viewBox="${viewBox}" xmlns="http://www.w3.org/2000/svg">`,
        `<path d="${data.d}" fill="${o.bgColor}" stroke="${o.borderColor}" transform="${data.transform}" />`,
        '</svg>'
    ].join('');

    // console.log(svg);
    const backgroundImage = `url("data:image/svg+xml;charset=utf8,${encodeURIComponent(svg)}")`;

    const background = `${backgroundImage} center no-repeat`;

    const padding = `${o.arrowSize + o.borderRadius}px`;

    const style = {
        background,
        backgroundImage,
        padding,
        changed: true
    };

    styleCache.position = info.position;
    styleCache[info.position] = {
        key,
        style
    };

    return style;
};
