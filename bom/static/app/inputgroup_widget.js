/**
 * Logic for the "inputgroup.html" Django widget.
 */

/** Example text when copying object properties in Fusion360. */
const FUSION_TEST_STRING = `
4b3vf09002_knob v1

Component Instances (1)
Area	5876.196 mm^2
Density	0.008 g / mm^3
Mass	43.721 g
Volume	5569.58 mm^3
Physical Material	Steel

Bounding Box
	Length 	 43.39 mm
	Width 	 43.39 mm
	Height 	 15.80 mm
World X,Y,Z	0.00 mm, 0.00 mm, 0.00 mm
Center of Mass	-47.344 mm, 63.319 mm, 69.742 mm

Moment of Inertia at Center of Mass   (g mm^2)
	Ixx = 5517.548
	Ixy = 1.705
	Ixz = 2.032
	Iyx = 1.705
	Iyy = 6080.789
	Iyz = -1.716
	Izx = 2.032
	Izy = -1.716
	Izz = 10728.587

Moment of Inertia at Origin   (g mm^2)
	Ixx = 393467.087
	Ixy = 131068.333
	Ixz = 144363.928
	Iyx = 131068.333
	Iyy = 316738.207
	Iyz = -193074.622
	Izx = 144363.928
	Izy = -193074.622
	Izz = 284019.488
 `


/**
 * Try to parse the `Mass` out of a Fusion360 properties string.
 * @throws Error if it cannot be parsed out.
 * @param string The resulting mass in KG.
 */
function fusion360_readMass(string) {
    const regex = /Mass\s+((\d*\.?\d+))\sg/gm;
    const matches = regex.exec(string);
    return parseInt(matches[1]) / 1000.0;
}

/**
 * Try to parse the Bounding Box out of a Fusion360 properties string.
 * @throws Error if it cannot be parsed out.
 * @param string The resulting AABB in Len x Width x Height (mm)
 */
function fusion360_readAABB(string) {
    const regLength = /\sLength\s+((\d*\.?\d+))\smm/gm;
    const regWidth = /\sWidth\s+((\d*\.?\d+))\smm/gm;
    const regHeight = /\sHeight\s+((\d*\.?\d+))\smm/gm;
    let getmm = (r) => r.exec(string)[1];
    return `${getmm(regLength)} x ${getmm(regWidth)} x ${getmm(regHeight)}`
}

/** Parser for the maths typed into calculator fields (expr-eval, not `eval`). */
const CALCULATOR_PARSER = (window.exprEval && new exprEval.Parser()) || null;

/**
 * Evaluate an arithmetic expression typed into a field, e.g. "12.5 * 4 + 3".
 * Plain arithmetic and the functions expr-eval knows (sqrt, round, ...) only;
 * no access to the page, unlike `eval`.
 * @returns The result, or `null` if the text is not a valid expression.
 */
function evaluateCalculation(text) {
    if (!CALCULATOR_PARSER) {
        console.error('expr-eval is not included on the page; calculator fields are disabled.');
        return null;
    }
    try {
        const result = CALCULATOR_PARSER.evaluate(`${text}`.trim());
        return Number.isFinite(result) ? result : null;
    } catch (error) {
        return null;
    }
}

/**
 * Evaluate maths on the cost and unit fields when Enter is pressed, replacing the
 * expression with its result. Invalid expressions are left as typed.
 * @param {} keyEvent The UI keydown event.
 */
function calculatePreventSubmit(keyEvent) {
    if (keyEvent.key === 'Enter' || keyEvent.keyCode === 13) {
        const result = evaluateCalculation(this.value);
        if (result !== null) {
            this.value = result;
            this.dispatchEvent(new Event('change', { bubbles: true }));
        }
        keyEvent.preventDefault();
        return false;
    }
}

// When the document is ready and all the fields have been added
// to the DOM, check to see if any have "bomnado-bomnado-calculator" on them.
// If they do, then process as a bomnado-calculator field.
document.addEventListener('DOMContentLoaded', () => {
    const calculators = document.querySelectorAll('.bomnado-calculator');
    calculators.forEach(field => field.addEventListener('keydown', calculatePreventSubmit));
});