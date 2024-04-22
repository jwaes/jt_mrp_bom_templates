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
                            # _logger.info("Templated BoM already exists ... re-creating")
                            # template_boms.unlink()
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
                            variant_bom.bom_line_ids.unlink()
                            variant_bom.write(variant_bom_vals)
                            for line in bom.bom_line_ids:
                                line_vals = {
                                    'bom_id': variant_bom.id,                                         
                                }
                                variant_bom_line = line.copy(line_vals)
                            
                        else:
                            variant_bom = bom.copy(variant_bom_vals)

                        # bom_msg = _("This BoM has been created from BoM Template")
                        # variant_bom.message_post(body=bom_msg)
                        variant_bom.message_post_with_view(
                            'mail.message_origin_link',
                            values={'self': variant_bom, 'origin': bom, 'edit': update},
                            subtype_id=self.env.ref('mail.mt_note').id)                  
                        
                        issues = []

                        # lines_per_seq = bom.bom_template_line_ids.grouped('sequence_bis')

                        for line in bom.bom_template_line_ids:
                            
                            applicable = True
                            if line.bom_product_template_attribute_value_ids:
                                applicable = len(line.bom_product_template_attribute_value_ids - variant.product_template_variant_value_ids) == 0

                            # if line.applicable_regexp:
                            #     pattern = re.compile(line.applicable_regexp)
                            #     applicable = bool(pattern.match(variant.default_code))

                            if applicable:  
                                prod = line._generate_bom_line(variant)
                                if not prod:
                                    _logger.warning("No matching product found!")
                                    issues.append(line.template_id)
                                    
                                else:
                                    _logger.info("Creating BoM Line")

                                    line_vals = {
                                        'product_id': prod.id,
                                        'product_qty': line.product_qty,
                                        'product_uom_id': line.product_uom_id.id,
                                        'sequence': line.sequence,
                                        'bom_id': variant_bom.id,                                    
                                    }

                                    bom_line = self.env['mrp.bom.line'].create(line_vals)
                            else:
                                _logger.info("BoM Line not applicable")

                        result.append({'variant': variant, 'applicable': True, 'issues':issues, 'message': None})
                source = False
                if self.env.context.get('bom_gen_source'):
                    source = self.env.context.get('bom_gen_source')
                bom.message_post_with_view(
                    'jt_mrp_bom_templates.message_bom_template_result',
                    values={'result': result, 'source': source},
                    subtype_id=self.env.ref('mail.mt_note').id)                                
                # rec.with_context(bom_gen_source='Because Attribute Set changed')._generate_template_boms()

    def obsolete(self):
        for bom in self:
            if bom.bom_template_id:
                bom.bom_template_id = False
                bom.code = "generated - obsolete (%s)" % bom.product_id.display_name
                bom.active = False        



class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line'

    parent_is_template = fields.Boolean('parent_is_template', related="bom_id.is_bom_template", default=False)

    sequence_bis = fields.Integer(compute='_compute_sequence_bis', inverse='_inverse_sequence_bis', string='Sequence')
    
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
                    if lines:
                        bom.message_post_with_view(
                            "jt_mrp_bom_templates.track_bom_template_2",
                            values={"lines": lines, "product_id": product_id},
                            subtype_id=self.env.ref("mail.mt_note").id,
                        )
            elif "product_qty" in values or "product_uom_id" in values:
                for bom in self.mapped("bom_id"):
                    lines = self.filtered(lambda l: l.bom_id == bom)
                    if lines:
                        product_qty = values.get("product_qty") or lines.product_qty
                        product_uom_id = values.get("product_uom_id")
                        if product_uom_id:
                            product_uom_id = self.env["uom.uom"].browse(product_uom_id)
                        product_uom_id = product_uom_id or lines.product_uom_id
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