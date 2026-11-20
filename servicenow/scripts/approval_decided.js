// SKR Cloud: approval decided (sysapproval_approver, after update). SYNTH-SKR-PROV
// Copies the first approve/reject decision onto the requested item, records who decided, and marks the other
// pending approvals as no longer required. The provisioning worker only builds items with u_cloud_approval = approved.
(function executeRule(current, previous /*null when async*/) {
    if (current.source_table != 'sc_req_item' || !current.state.changes())
        return;
    var decision = current.getValue('state');
    if (decision != 'approved' && decision != 'rejected')
        return;
    var ritm = new GlideRecord('sc_req_item');
    if (!ritm.get(current.getValue('sysapproval')) || ritm.cat_item.category.title != 'SKR Cloud (Azure)')
        return;
    if (ritm.getValue('u_cloud_approval') != 'requested')
        return;                                   // already decided by another approver
    var who = current.getValue('approver');
    if (who == ritm.getValue('requested_for') || who == ritm.getValue('opened_by')) {
        ritm.work_notes = current.approver.getDisplayValue() + ' cannot approve their own request: decision ignored.';
        ritm.update();
        return;                                   // separation of duties, even if an approval was added by hand
    }
    ritm.u_cloud_approval = decision;             // set first: the hold rule copies it to approval
    ritm.approval = decision;
    if (decision == 'approved') {
        ritm.stage = 'fulfillment';
    } else {
        ritm.state = 4;                           // Closed Incomplete
    }
    var note = (decision == 'approved' ? 'Approved' : 'Rejected') + ' by ' + current.approver.getDisplayValue();
    if (current.comments.getJournalEntry(1))
        note += ': ' + current.comments.getJournalEntry(1);
    ritm.work_notes = note;
    ritm.update();
    var others = new GlideRecord('sysapproval_approver');
    others.addQuery('sysapproval', ritm.getUniqueValue());
    others.addQuery('state', 'requested');
    others.addQuery('sys_id', '!=', current.getUniqueValue());
    others.query();
    while (others.next()) {
        others.state = 'not_required';
        others.update();
    }
})(current, previous);
