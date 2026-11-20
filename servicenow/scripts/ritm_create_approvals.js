// SKR Cloud: create approvals (sc_req_item, after insert). SYNTH-SKR-PROV
// One approval per active member of the SKR Cloud Platform group; the first decision counts.
// Separation of duties: nobody approves a request they opened or that is for them.
(function executeRule(current, previous /*null when async*/) {
    if (current.cat_item.category.title != 'SKR Cloud (Azure)')
        return;
    var grp = new GlideRecord('sys_user_group');
    if (!grp.get('name', 'SKR Cloud Platform')) {
        current.work_notes = 'No approver group "SKR Cloud Platform" found: the request cannot be approved.';
        current.update();
        return;
    }
    var m = new GlideRecord('sys_user_grmember');
    m.addQuery('group', grp.getUniqueValue());
    m.addQuery('user.active', true);
    m.query();
    var n = 0, skipped = [];
    var requester = current.getValue('requested_for'), opener = current.getValue('opened_by');
    while (m.next()) {
        var who = m.getValue('user');
        if (who == requester || who == opener) {
            skipped.push(m.user.getDisplayValue());
            continue;
        }
        var a = new GlideRecord('sysapproval_approver');
        a.initialize();
        a.approver = m.user;
        a.sysapproval = current.getUniqueValue();
        a.document_id = current.getUniqueValue();
        a.source_table = 'sc_req_item';
        a.state = 'requested';
        a.insert();
        n++;
    }
    if (n == 0) {
        current.work_notes = 'No eligible approver: ' + (skipped.length ? skipped.join(', ') +
            ' cannot approve their own request. ' : '') + 'Add another member to the SKR Cloud Platform group.';
        current.update();
    } else if (skipped.length) {
        current.work_notes = skipped.join(', ') + ' not asked to approve: they raised this request.';
        current.update();
    }
    gs.info('SYNTH-SKR-PROV: ' + n + ' approval(s) requested for ' + current.number);
})(current, previous);
