import logging
import re
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class MrpBom(models.Model):
    _name = "mrp.bom"
    _inherit = ['mrp.bom', 'mail.activity.mixin']

    is_bom_template = fields.Boolean('Is Template', default=False, tracking=True)

    bom_template_line_ids = fields.One2many('mrp.bom.template.line', 'bom_id', 'BoM Template Lines', copy=True, tracking=True)

    allowed_product_attribute_ids = fields.One2many('product.attribute', compute='_compute_allowed_product_attribute_ids', string='Allowed PRoduct ATtribute Ids')

    bom_template_id = fields.Many2one('mrp.bom', string='Bom Template', readonly=True, tracking=True)

    related_bom_ids = fields.One2many('mrp.bom', 'bom_template_id', string='Related Bom')

    related_bom_count = fields.Integer(compute='_compute_related_bom_count', string='Related BoM Count')


    product_id = fields.Many2one(tracking=True)
    product_tmpl_id = fields.Many2one(tracking=True)
    product_qty = fields.Float(tracking=True)
    picking_type_id = fields.Many2one(tracking=True) 

    
    @api.depends('related_bom_ids')
    def _compute_related_bom_count(self):
        for bom in self:
            bom.related_bom_count = len(bom.related_bom_ids)

    
    @api.depends('product_tmpl_id', 'product_tmpl_id.valid_product_template_attribute_line_ids')
    def _compute_allowed_product_attribute_ids(self):
        for bom in self:
            bom.allowed_product_attribute_ids = bom.product_tmpl_id.valid_product_template_attribute_line_ids.attribute_id

    @api.depends('product_tmpl_id', 'product_id', 'is_bom_template')
    def _compute_display_name(self):
        for bom in self:
            # name = ('[BoM Template] for' if bom.is_bom_template else '[BoM] for') + (bom.product_id.display_name if bom.product_id else product_templ_id.display_name)
            prefix = '[BoM Template] ' if bom.is_bom_template else '[BoM] '
            product_name = bom.product_tmpl_id.display_name
            if bom.product_id:
                product_name = bom.product_id.display_name
            name = prefix + product_name
            bom.display_name = name


    def write(self, values):
        bom_line_ids = {}
        if "bom_line_ids" in values:
            for bom in self:
                del_lines = []
                for line in values["bom_line_ids"]:
                    if line[0] == 2:
                        del_lines.append(line[1])
                if del_lines:
                    bom.message_post_with_view(
                        "jt_mrp_bom_templates.track_bom_template",
                        values={
                            "lines": self.env["mrp.bom.line"].browse(del_lines),
                            "mode": "Removed",
                        },
                        subtype_id=self.env.ref("mail.mt_note").id,
                    )
                bom_line_ids[bom.id] = bom.bom_line_ids

        res = super(MrpBom, self).write(values)

        if 'is_bom_template' in values:
            if values['is_bom_template']:
                self.active = False
                self.bom_template_id = False
                self.product_id = False
                self.code = 'TEMPLATE'

        if "bom_line_ids" in values:
            for bom in self:
                new_lines = bom.bom_line_ids - bom_line_ids[bom.id]
                if new_lines:
                    bom.message_post_with_view(
                        "jt_mrp_bom_templates.track_bom_template",
                        values={"lines": new_lines, "mode": "New"},
                        subtype_id=self.env.ref("mail.mt_note").id,
                    )
        return res

    def action_related_bom(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("mrp.mrp_bom_form_action")
        action['domain'] = [('bom_template_id', '=', self.id)]
        return action        

    def _generate_template_boms(self):
        for bom in self:
            if not bom.is_bom_template:
                _logger.info("BoM %s with id %s is not a template ... skipping", bom, bom.id)
            else:
                tmpl = bom.product_tmpl_id
                result = []
                for variant in tmpl.product_variant_ids:
                    boms = variant.variant_bom_ids
                    template_boms = boms
                    message = []
                    if boms:
                        template_boms = boms.filtered(lambda r: r.bom_template_id == bom)
                    if len(template_boms) > 1:
                        _logger.error("More than 1 templated bom found ...")
                        message.append("Found multiple Templated BoM for variant %s" % variant.display_name)
                    else: 
                        update = False
                        if len(template_boms) == 1:
                            update = True
                            _logger.info("Templated BoM already exists ... needs updating")
                        else :
                            _logger.info("No templated BoM found ... creating")

                        variant_bom_vals = {
                            'is_bom_template' : False,
                            'active' : True,                            
                            'bom_template_line_ids' : [],
                            'bom_template_id' : bom.id,
                            'product_id' : variant.id,
                            'code': 'generated',
                        }

                        if update:
                            variant_bom = template_boms[:1]
                            variant_bom.write(variant_bom_vals)
                            _logger.info("Updated variant_bom [%s]", variant_bom.id)
                        else:
                            variant_bom_vals['bom_line_ids'] = False
                            variant_bom = bom.copy(variant_bom_vals)
                            _logger.info("Created variant_bom [%s]", variant_bom.id)

                        obsolete_lines = variant_bom.bom_line_ids

                        for line in bom.bom_line_ids:                            
                            if line.bom_product_template_attribute_value_ids:
                                init_len = len(line.bom_product_template_attribute_value_ids)
                                calculated_len = len(line.bom_product_template_attribute_value_ids - variant.product_template_variant_value_ids)
                                if calculated_len == init_len:
                                    _logger.info("Template BoM Line for %s NOT Applicable", line.product_id.name)
                                    continue

                            _logger.info("Template BoM Line for %s ", line.product_id.name)
                            existing_line = None
                            if variant_bom.bom_line_ids:
                                existing_line = variant_bom.bom_line_ids.filtered(lambda r: r.template_bom_line_id.id == line.id)
                            line_vals = {
                                'bom_id': variant_bom.id,
                                'template_bom_line_id': line.id,
                            }
                            variant_bom_line = None
                            if existing_line is not None and len(existing_line) == 1:
                                    _logger.info("Existing Line from tepmplate line [%s] found", existing_line.template_bom_line_id.id)
                                    all_vals = line.copy_data()[0]
                                    all_vals.update(line_vals)
                                    all_vals.update(line_vals)
                                    all_vals['bom_product_template_attribute_value_ids'] = False
                                    existing_line.write(all_vals)
                                    variant_bom_line = existing_line
                                    _logger.info("Updated Line from template line [%s] for product %s", variant_bom_line.template_bom_line_id.id, variant_bom_line.product_id.name)
                                    obsolete_lines = obsolete_lines - variant_bom_line
                            else:                                
                                variant_bom_line = line.copy(line_vals)
                                _logger.info("Create Line from template line [%s] for product %s", variant_bom_line.template_bom_line_id.id, variant_bom_line.product_id.name)
                            
                        obsolete_lines.unlink()

                        variant_bom.message_post_with_view(
                            'mail.message_origin_link',
                            values={'self': variant_bom, 'origin': bom, 'edit': update},
                            subtype_id=self.env.ref('mail.mt_note').id)                  
                        
                        issues = []

                        # foo = bom.bom_template_line_ids
                        # grouped = foo.read_group([], fields=['id'], group_by=['sequence_bis'])

                        to_be_resolved_seq = list(set(bom.bom_template_line_ids.mapped('sequence_bis')))
                        for line in bom.bom_template_line_ids:
                            if line.sequence_bis not in to_be_resolved_seq:
                                _logger.info("BoM Line already matched for line sequence %s", line.sequence_bis)
                                continue
                            
                            applicable = True
                            if line.bom_product_template_attribute_value_ids:
                                applicable = len(line.bom_product_template_attribute_value_ids - variant.product_template_variant_value_ids) == 0
                                _logger.info("BoM Line explicitly included")

                            if line.bom_product_template_excl_attribute_value_ids:
                                init_len = len(line.bom_product_template_excl_attribute_value_ids)
                                calculated_len = len(line.bom_product_template_excl_attribute_value_ids - variant.product_template_variant_value_ids)
                                applicable = (calculated_len == init_len)
                                _logger.info("BoM Line explicitly excluded")

                            # if line.applicable_regexp:
                            #     appl = bool(re.search(line.applicable_regexp, ))



                            if applicable:  
                                prod = line._generate_bom_line(variant)
                                if not prod:
                                    if not line.optional:
                                        _logger.warning("No matching product found!")
                                        # issues.append(line.template_id)                                    
                                else:

                                    to_be_resolved_seq.remove(line.sequence_bis)
                                    
                                    _logger.info("Creating BoM Line")

                                    line_vals = {
                                        'product_id': prod.id,
                                        'product_qty': line.product_qty,
                                        'product_uom_id': line.product_uom_id.id,
                                        'sequence': line.sequence,
                                        'bom_id': variant_bom.id,
                                        'bom_template_line_id': line.id,
                                    }
                                    
                                    existing_line = variant_bom.bom_line_ids.filtered(lambda r: r.bom_template_line_id.id == line.id)

                                    if existing_line is not None and len(existing_line) == 1:
                                        _logger.info("Existing Line from bom tepmplate line [%s] found", existing_line.template_bom_line_id.id)
                                        existing_line.write(line_vals)
                                        variant_bom_line = existing_line
                                        _logger.info("Updated Line from template line [%s] for product %s", variant_bom_line.template_bom_line_id.id, variant_bom_line.product_id.name)
                                    else:                                
                                        variant_bom_line = self.env['mrp.bom.line'].create(line_vals)
                                        _logger.info("Created Line from bom template line [%s] for product %s", line.id, variant_bom_line.product_id.name)
                            else:
                                _logger.info("BoM Line not applicable")
                        
                        if len(to_be_resolved_seq) > 0:
                            _logger.info("Not all Lines resolved")
                            for seq in to_be_resolved_seq:
                                concerned_lines = bom.bom_template_line_ids.filtered(lambda r : r.sequence_bis == seq)
                                _logger.info("Concerned lines: %s", concerned_lines)
                                for line in concerned_lines:
                                    # Do not raise issue if there is an explicit exlude
                                    if line.bom_product_template_excl_attribute_value_ids:
                                        if len(line.bom_product_template_excl_attribute_value_ids - variant.product_template_variant_value_ids) < len(line.bom_product_template_excl_attribute_value_ids):
                                            _logger.info("skipping - excluded")
                                            continue
                                    _logger.info("not excluded - issue !")
                                    issues.append(line.template_id)


                        variant_bom.bom_line_ids.filtered(lambda r: r.bom_template_line_id and r.bom_template_line_id not in bom.bom_template_line_ids).unlink()

                        result.append({'variant': variant, 'applicable': True, 'issues':issues, 'message': None})
                source = False
                if self.env.context.get('bom_gen_source'):
                    source = self.env.context.get('bom_gen_source')
                bom.message_post_with_view(
                    'jt_mrp_bom_templates.message_bom_template_result',
                    values={'result': result, 'source': source},
                    subtype_id=self.env.ref('mail.mt_note').id)                                

    def obsolete(self):
        for bom in self:
            if bom.bom_template_id:
                bom.bom_template_id = False
                bom.code = "generated - obsolete (%s)" % bom.product_id.display_name
                bom.active = False        



class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line'

    parent_is_template = fields.Boolean('parent_is_template', related="bom_id.is_bom_template")

    sequence_bis = fields.Integer(compute='_compute_sequence_bis', inverse='_inverse_sequence_bis', string='Sequence*')

    template_bom_line_id = fields.Many2one('mrp.bom.line', string='template_bom_line')

    bom_template_line_id = fields.Many2one('mrp.bom.template.line', string='bom_template_line')
    
    @api.depends('sequence')
    def _compute_sequence_bis(self):
        for rec in self:
            rec.sequence_bis = rec.sequence

    def _inverse_sequence_bis(self):
        for rec in self:
            rec.sequence = rec.sequence_bis    

    def write(self, values):
            if "product_id" in values:
                for bom in self.mapped("bom_id"):
                    lines = self.filtered(lambda l: l.bom_id == bom)
                    product_id = values.get("product_id")
                    if product_id:
                        product_id = self.env["product.product"].browse(product_id)
                    product_id = product_id or lines.product_id

                    lines = lines.filtered(lambda l: l.product_id.id != product_id.id)

                    if lines:
                        bom.message_post_with_view(
                            "jt_mrp_bom_templates.track_bom_template_2",
                            values={"lines": lines, "product_id": product_id},
                            subtype_id=self.env.ref("mail.mt_note").id,
                        )
            if "product_qty" in values or "product_uom_id" in values:
                for bom in self.mapped("bom_id"):
                    lines = self.filtered(lambda l: l.bom_id == bom)
                    if lines:
                        product_qty = values.get("product_qty") or lines.product_qty
                        product_uom_id = values.get("product_uom_id")
                        if product_uom_id:
                            product_uom_id = self.env["uom.uom"].browse(product_uom_id)
                        product_uom_id = product_uom_id or lines.product_uom_id

                        lines = lines.filtered(lambda r: r.product_qty != product_qty or r.product_uom_id != product_uom_id)
                        if lines:
                            bom.message_post_with_view(
                                "jt_mrp_bom_templates.track_bom_line_template",
                                values={
                                    "lines": lines,
                                    "product_qty": product_qty,
                                    "product_uom_id": product_uom_id,
                                },
                                subtype_id=self.env.ref("mail.mt_note").id,
                            )
            return super(MrpBomLine, self).write(values)                