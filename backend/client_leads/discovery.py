"""SQL discovery filters with shared authorization for rows and counts."""

import re

from backend.client_leads.details import decode
from backend.database import get_db


def integer(value, label, maximum=9223372036854775807):
    """Reject invalid IDs, pagination values and integer overflow."""
    if not str(value).isdigit() or not 1 <= int(value) <= maximum:
        raise ValueError('Invalid ' + label)
    return int(value)


def options(user):
    """Return scoped creators and read-only source selection options."""
    from backend.client_leads.routes import visibility

    scope, parameters = visibility(user)
    connection = get_db()
    try:
        people = connection.execute(
            'SELECT DISTINCT u.id, u.username FROM client_leads l '
            'JOIN users u ON u.id = l.created_by WHERE (' + scope + ') '
            'ORDER BY u.username', parameters,
        ).fetchall()
        sources = connection.execute(
            'SELECT id, name, source_type FROM enquiry_sources '
            "WHERE is_active = 1 AND source_type IN ('email', 'whatsapp') "
            "AND contact_value IS NOT NULL AND contact_value != '' "
            'ORDER BY name COLLATE NOCASE'
        ).fetchall()
        historical = connection.execute(
            'SELECT DISTINCT src.id, src.name, src.is_active '
            'FROM client_leads l JOIN users u ON u.id = l.created_by '
            'JOIN enquiry_sources src ON src.id = l.enquiry_source_id '
            'WHERE (' + scope + ') AND src.is_active = 0', parameters,
        ).fetchall()
        return {'filter_sources': [dict(row) for row in sources]
                + [dict(row) for row in historical],
                'creators': [dict(row) for row in people],
                'sources': [dict(row) for row in sources]}
    finally:
        connection.close()


def discover(user, args):
    """Scope rows, counts and pagination with the same SQL filters."""
    from backend.client_leads.routes import lead_query

    sql, parameters = lead_query(user)
    page = integer(args.get('page', '1'), 'page', 1000000)
    size = integer(args.get('page_size', '25'), 'page size', 100)
    search = args.get('q', '').strip()
    if len(search) > 200:
        raise ValueError('Search is limited to 200 characters.')
    if search:
        pattern = '%' + search.replace('!', '!!').replace('%', '!%').replace(
            '_', '!_') + '%'
        fields = ['l.name', 'l.company', 'l.email', 'l.phone']
        conditions = [field + " LIKE ? ESCAPE '!'" for field in fields]
        parameters.extend([pattern] * len(fields))
        conditions += [
            "EXISTS (SELECT 1 FROM json_each(l.contact_persons_json) c "
            "WHERE json_extract(c.value, '$.name') LIKE ? ESCAPE '!' "
            "OR json_extract(c.value, '$.email') LIKE ? ESCAPE '!' "
            "OR json_extract(c.value, '$.phone') LIKE ? ESCAPE '!')",
            "EXISTS (SELECT 1 FROM json_each(l.emails_json) e "
            "WHERE e.value LIKE ? ESCAPE '!')",
            "EXISTS (SELECT 1 FROM json_each(l.phones_json) p "
            "WHERE p.value LIKE ? ESCAPE '!')",
        ]
        parameters.extend([pattern] * 5)
        digits = re.sub(r'[^0-9]', '', search)
        if len(digits) >= 3 and re.fullmatch(r'[+0-9 ()\-.]+', search):
            conditions.append(
                "replace(replace(replace(replace(replace(l.phone, ' ', ''), "
                "'-', ''), '(', ''), ')', ''), '+', '') LIKE ?"
            )
            parameters.append('%' + digits + '%')
            conditions.extend([
                "EXISTS (SELECT 1 FROM json_each(l.contact_persons_json) c "
                "WHERE json_extract(c.value, '$.phone') LIKE ?)",
                "EXISTS (SELECT 1 FROM json_each(l.phones_json) p "
                "WHERE p.value LIKE ?)",
            ])
            parameters.extend(['%' + digits + '%'] * 2)
        sql += ' AND (' + ' OR '.join(conditions) + ')'
    for field in ('status', 'active', 'access', 'ownership'):
        value = args.get(field, 'all')
        if field == 'status':
            if value not in ('all', 'lead', 'prospect', 'customer'):
                raise ValueError('Invalid client status filter.')
            if value != 'all':
                sql += ' AND l.status = ?'
                parameters.append(value)
        elif field == 'active':
            if value not in ('all', 'active', 'inactive'):
                raise ValueError('Invalid availability filter.')
            if value != 'all':
                sql += ' AND l.is_active = ?'
                parameters.append(int(value == 'active'))
        elif field == 'ownership':
            if value not in ('all', 'own', 'others'):
                raise ValueError('Invalid ownership filter.')
            if value != 'all':
                sql += ' AND l.created_by ' + ('=' if value == 'own' else '!=')
                sql += ' ?'
                parameters.append(user['id'])
        elif value != 'all':
            if value not in ('VIEW', 'EDIT', 'shared'):
                raise ValueError('Invalid access filter.')
            sql += (' AND EXISTS (SELECT 1 FROM client_lead_shares s '
                    'WHERE s.lead_id = l.id AND s.user_id = ? '
                    'AND s.is_active = 1')
            parameters.append(user['id'])
            if value != 'shared':
                sql += ' AND s.access_level = ?'
                parameters.append(value)
            sql += ')'
    for field, column in (('creator', 'created_by'),
                          ('source', 'enquiry_source_id')):
        if args.get(field):
            sql += ' AND l.' + column + ' = ?'
            parameters.append(integer(args[field], field))
    sorts = {'created': 'l.created_at', 'name': 'l.name COLLATE NOCASE',
             'company': 'l.company COLLATE NOCASE', 'status': 'l.status'}
    sort = args.get('sort', 'created')
    direction = args.get('direction', 'desc')
    if sort not in sorts or direction not in ('asc', 'desc'):
        raise ValueError('Invalid sorting option.')
    connection = get_db()
    try:
        # One read transaction gives consistent totals and rows during updates.
        connection.execute('BEGIN')
        total = connection.execute(
            'SELECT COUNT(*) FROM (' + sql + ')', parameters
        ).fetchone()[0]
        rows = connection.execute(
            sql + ' ORDER BY ' + sorts[sort] + ' ' + direction + ', l.id '
            + direction + ' LIMIT ? OFFSET ?',
            [*parameters, size, (page - 1) * size],
        ).fetchall()
        return {'leads': [decode(row) for row in rows], 'total': total,
                'page': page, 'page_size': size,
                'pages': (total + size - 1) // size}
    finally:
        connection.close()
