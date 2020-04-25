{% for section in sections %}
{% set underline = "-" %}
{% if section %}
{{section}}
{{ underline * section|length }}{% set underline = "~" %}

{% endif %}
{% if sections[section] %}
{% for category, val in definitions.items() if category in sections[section] and category != 'trivial' %}

{{ definitions[category]['name'] }}
{{ underline * definitions[category]['name']|length }}

{% if definitions[category]['showcontent'] %}
{% for text, values in sections[section][category]|dictsort(by='value') %}
- {{ text }}{% if category != 'process' %}
  {{ values|sort|join(',\n  ') }}
  {% endif %}

{% endfor %}
{% else %}
- {{ sections[section][category]['']|sort|join(', ') }}


{% endif %}
{% if sections[section][category]|length == 0 %}

No significant changes.


{% else %}
{% endif %}
{% endfor %}
{% else %}

No significant changes.


{% endif %}
{% endfor %}
