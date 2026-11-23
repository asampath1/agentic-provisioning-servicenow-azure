// SKR Cloud: hold approval (sc_req_item, before update). SYNTH-SKR-PROV
// u_cloud_approval is the gate: only "SKR Cloud: approval decided" sets it, from a person's decision. On this PDI
// the out-of-box "Service Catalog Request" flow auto-approves requests under $1000 and copies that onto the item;
// this rule keeps the item's approval in line with u_cloud_approval, so it never shows Approved before a person
// has approved it. The provisioning worker builds only when u_cloud_approval = approved.
// It also keeps the stage in line with u_provisioning_state (see below).
(function executeRule(current, previous /*null when async*/) {
    var gate = current.getValue('u_cloud_approval');
    if (!gate || current.cat_item.category.title != 'SKR Cloud (Azure)')
        return;
    if (current.getValue('approval') != gate)
        current.approval = gate;
    if (gate == 'requested' && current.getValue('stage') != 'waiting_for_approval')
        current.stage = 'waiting_for_approval';
    // The stage follows the worker's provisioning state (ServiceNow ignores stage written over the REST API):
    // built and in use -> Delivery; deleted on expiry -> Completed.
    var stageFor = {succeeded: 'delivery', deleted: 'complete'}[current.getValue('u_provisioning_state')];
    if (stageFor && current.getValue('stage') != stageFor)
        current.stage = stageFor;
})(current, previous);
