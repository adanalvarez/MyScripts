#!/usr/bin/env python3

import sys
import json
from pathlib import Path

HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Dependency Report for {repo_name}</title>
  <style>
    /* Full-page background color #8ECAE6 */
    body {{
      margin: 0;
      padding: 0;
      font-family: "Segoe UI", Tahoma, Geneva, Verdana, sans-serif;
      background-color: #8ECAE6;
      color: #333;
    }}

    /* Header banner */
    .header {{
      background-color: #023047;
      color: #fff;
      padding: 20px;
      text-align: center;
      box-shadow: 0 2px 4px rgba(0,0,0,0.2);
    }}
    .header h1 {{
      margin: 0;
      font-size: 1.8em;
      letter-spacing: 1px;
    }}

    /* Main container as a white card */
    .container {{
      max-width: 1200px;
      margin: 20px auto 60px auto;
      background-color: #FFFFFF;
      border-radius: 6px;
      box-shadow: 0 1px 4px rgba(0,0,0,0.2);
      padding: 20px;
    }}

    h2 {{
      margin-top: 0;
      color: #219EBC;
    }}

    /* Table styling */
    .table-responsive {{
      width: 100%;
      overflow-x: auto;
      margin-bottom: 2em;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: #fff;
      border-radius: 6px;
      overflow: hidden;
      min-width: 600px;  /* ensures scrolling if contents are very wide */
      box-shadow: 0 1px 3px rgba(0,0,0,0.1);
      table-layout: auto;
    }}
    thead tr {{
      background-color: #219EBC;
      color: #fff;
    }}
    th, td {{
      padding: 12px 16px;
      border-bottom: 1px solid #eee;
      vertical-align: top;
      word-wrap: break-word;  /* allow wrapping within cells */
      white-space: pre-wrap;  /* or 'normal' */
    }}
    th {{
      text-align: left;
      font-weight: 600;
    }}
    tr:last-child td {{
      border-bottom: none;
    }}

    /* Dependencies & warnings lists */
    .dependencies-list, .warnings-list {{
      list-style: none;
      margin: 0;
      padding-left: 1.2em;
    }}
    .dependencies-list li::before {{
      content: "• ";
      color: #219EBC;
    }}
    .warnings-list li::before {{
      content: "⚠ ";
      color: #d00;
    }}
    .no-warnings {{
      color: #666;
      font-style: italic;
    }}

    /* Collapsible styling */
    .collapsible-section {{
      background: #fff;
      margin-bottom: 2em;
      padding: 1em;
      border-radius: 6px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }}
    .toggle-btn {{
      background-color: #219EBC;
      color: #fff;
      border: none;
      padding: 0.6em 1em;
      border-radius: 4px;
      cursor: pointer;
      font-size: 1em;
      margin-bottom: 1em;
      box-shadow: 0 2px 3px rgba(0,0,0,0.1);
    }}
    .toggle-btn:hover {{
      background-color: #188bb2;
    }}
    .toggle-btn:active {{
      background-color: #127294;
    }}

    /* Footer */
    .footer {{
      text-align: center;
      margin-top: 2em;
      font-size: 0.9em;
      color: #666;
    }}
  </style>
  <script>
    function toggleHidden(id) {{
      const el = document.getElementById(id);
      if (el.style.display === 'none') {{
        el.style.display = 'block';
      }} else {{
        el.style.display = 'none';
      }}
    }}
  </script>
</head>
<body>

<div class="header">
  <h1>Dependency Report for {repo_name}</h1>
</div>

<div class="container">

  <h2>Key Actions</h2>
  <div class="table-responsive">
    <table>
      <thead>
        <tr>
          <th style="width: 30%;">Action</th>
          <th style="width: 35%;">Dependencies</th>
          <th style="width: 35%;">Docker Warnings</th>
        </tr>
      </thead>
      <tbody>
        {main_table_rows}
      </tbody>
    </table>
  </div>

  {collapsed_section}

</div>

</body>
</html>
"""


def main():
    """
    Usage:
      python generate_html_report.py <repo_name> <input_json> <output_html>
    """
    if len(sys.argv) < 4:
        print("Usage: python generate_html_report.py <repo_name> <input_json> <output_html>")
        sys.exit(1)

    repo_name = sys.argv[1]
    input_json = Path(sys.argv[2])
    output_html = Path(sys.argv[3])

    if not input_json.is_file():
        print(f"Error: JSON file not found: {input_json}")
        sys.exit(1)

    # Load the data
    try:
        data = json.loads(input_json.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Error parsing JSON: {e}")
        sys.exit(1)

    dependencies = data.get("dependencies", {})
    docker_warnings = data.get("docker_warnings", {})

    # We'll separate "important" from "less important" actions:
    # - "important" if it has dependencies or warnings
    # - "less" if it has no dependencies AND no warnings
    main_table_html = []
    less_important_list = []

    for parent, child_list in dependencies.items():
        # Convert child_list -> bullet list
        if child_list:
            deps_html = "".join(f"<li>{c}</li>" for c in child_list)
            deps_html = f'<ul class="dependencies-list">{deps_html}</ul>'
        else:
            deps_html = '<em>No further dependencies</em>'

        # Docker warnings
        warnings_list = docker_warnings.get(parent, [])
        if warnings_list:
            warn_html = "".join(f"<li>{w}</li>" for w in warnings_list)
            warn_html = f'<ul class="warnings-list">{warn_html}</ul>'
        else:
            warn_html = '<span class="no-warnings">No warnings</span>'

        # Check if "less important"
        if not child_list and not warnings_list:
            less_important_list.append(parent)
        else:
            row_html = f"""
            <tr>
              <td><strong>{parent}</strong></td>
              <td>{deps_html}</td>
              <td>{warn_html}</td>
            </tr>
            """
            main_table_html.append(row_html)

    main_table_rows = "".join(main_table_html)

    # Build the collapsed section for less important actions
    if less_important_list:
        # We'll also wrap this table in a .table-responsive
        li_rows = []
        for parent in less_important_list:
            row = f"""
            <tr>
              <td><strong>{parent}</strong></td>
              <td><em>No further dependencies</em></td>
              <td><span class="no-warnings">No warnings</span></td>
            </tr>
            """
            li_rows.append(row)

        collapsed_section = f"""
        <div class="collapsible-section">
          <h2>Less Important (No Dependencies &amp; No Warnings)</h2>
          <button class="toggle-btn" onclick="toggleHidden('lessImportantTable')">Show/Hide</button>
          <div id="lessImportantTable" style="display:none;">
            <div class="table-responsive">
              <table>
                <thead>
                  <tr>
                    <th style="width: 30%;">Action</th>
                    <th style="width: 35%;">Dependencies</th>
                    <th style="width: 35%;">Docker Warnings</th>
                  </tr>
                </thead>
                <tbody>
                  {''.join(li_rows)}
                </tbody>
              </table>
            </div>
          </div>
        </div>
        """
    else:
        collapsed_section = ""

    final_html = HTML_TEMPLATE.format(
        repo_name=repo_name,
        main_table_rows=main_table_rows,
        collapsed_section=collapsed_section
    )

    output_html.write_text(final_html, encoding="utf-8")
    print(f"HTML report generated: {output_html}")


if __name__ == "__main__":
    main()