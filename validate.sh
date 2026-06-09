#!/bin/bash
# Pre-deploy validation — catches JS syntax errors before they reach Render
FILE="$1"
echo "=== Validating $FILE ==="

# 1. Check for bare English words in JS section
JS_START=$(grep -n '<script>' "$FILE" | head -1 | cut -d: -f1)
JS_END=$(grep -n '</script>' "$FILE" | tail -1 | cut -d: -f1)
sed -n "${JS_START},${JS_END}p" "$FILE" > /tmp/js_check.txt

# 2. Check parentheses balance
OPEN=$(grep -o '(' /tmp/js_check.txt | wc -l)
CLOSE=$(grep -o ')' /tmp/js_check.txt | wc -l)
if [ "$OPEN" -ne "$CLOSE" ]; then
    echo "❌ PARENS UNBALANCED: $OPEN open, $CLOSE close (diff: $((OPEN - CLOSE)))"
    exit 1
fi
echo "✅ Parens balanced ($OPEN)"


# 4. Check for common patterns that break JS
if grep -q "onclick=.*D('[a-z]*').*'" "$FILE"; then
    echo "⚠️ Potential onclick quote issue (D('...') inside double quotes)"
fi

# 5. Check console.log is valid
if grep -q "console.log('.*$" /tmp/js_check.txt; then
    echo "❌ Unterminated console.log string"
    exit 1
fi

echo "✅ Validation passed"
