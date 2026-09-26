import re

def clean_climbing_text(input_file, output_file):
    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Remove Source Tags: e.g., ""
    content = re.sub(r'\\', '', content)

    # 2. Remove Page Numbers/Artifacts: Standalone numbers on lines
    # (Matches numbers surrounded by whitespace/newlines)
    content = re.sub(r'\n\s*\d+\s*\n', '\n', content)

    # 3. Join Hyphenated Words: e.g., "ent-\n hielt" -> "enthielt"
    # This looks for a '-' followed by a newline and optional spaces
    content = re.sub(r'(\w+)-\s*\n\s*(\w+)', r'\1\2', content)

    # 4. Join Broken Lines: 
    # Joins lines that don't end in a sentence-ending punctuation 
    # or where the next line starts with a lowercase letter.
    lines = content.splitlines()
    cleaned_lines = []
    
    if lines:
        current_line = lines[0].strip()
        for next_line in lines[1:]:
            next_line = next_line.strip()
            if not next_line:
                cleaned_lines.append(current_line)
                cleaned_lines.append("") # Keep paragraph breaks
                current_line = ""
                continue
            
            # Logic: If current line doesn't end in [.!?:] and next is lowercase
            # OR if it's clearly a continuation of a sentence.
            if current_line and not re.search(r'[.!?»"]$', current_line):
                current_line += " " + next_line
            else:
                if current_line:
                    cleaned_lines.append(current_line)
                current_line = next_line
        
        if current_line:
            cleaned_lines.append(current_line)

    # 5. Final Cleanup: Remove multiple spaces and empty lines
    final_text = "\n".join(cleaned_lines)
    final_text = re.sub(r' +', ' ', final_text) # Multiple spaces to single
    final_text = re.sub(r'\n{3,}', '\n\n', final_text) # Max two newlines

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(final_text)
    
    print(f"Cleanup complete! Saved to {output_file}")

# Usage
clean_climbing_text('Der einsame Sieg _ Mount Everes - Habeler, Peter.txt', 'cleaned_text.txt')